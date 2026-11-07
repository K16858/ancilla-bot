import asyncio
import subprocess
import threading
from datetime import datetime, timedelta

import pytest

from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import autoheal, channel, events, incidents, operations, store
from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import status as st
from ancilla_bot.node import daemon
from ancilla_bot.node.execute import Executor

YAML = """
hosts:
  - {id: h1, name: H1, os: ubuntu, node: true}
  - {id: h2, name: H2, os: ubuntu, node: true}
services:
  - {id: base, name: Base, host: h2, kind: systemd, unit: basesvc}
  - {id: web, name: Web, host: h1, kind: systemd, unit: nginx, actions: {restart: auto}}
  - {id: app, name: App, host: h1, kind: systemd, unit: appsvc, depends_on: [base], actions: {restart: auto}}
  - {id: dry, name: Dry, host: h1, kind: systemd, unit: dry1, actions: {restart: auto_dry_run}}
  - {id: appr, name: Appr, host: h1, kind: systemd, unit: apprsvc, actions: {restart: approval}}
  - {id: bare, name: Bare, host: h1, kind: systemd, unit: baresvc}
"""


class Env:
    host_state = "healthy"
    node_fresh = True
    connected = True
    svc_state = "healthy"  # 再起動後の検証で見える状態

    def __init__(self):
        self.host_flags, self.sent, self.notes = [], [], []


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    p = tmp_path / "h.yaml"
    p.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("ANCILLA_HOMELAB_PATH", str(p))
    monkeypatch.setattr(inv, "_cache", None)
    notes = []
    for m in (autoheal, operations, incidents):
        monkeypatch.setattr(m, "append_notification", lambda **k: notes.append(k["message"]))
    return notes


@pytest.fixture
def env(base, monkeypatch):
    e = Env()
    e.notes = base
    monkeypatch.setattr(channel, "REPORT_INTERVAL_SEC", 0)
    monkeypatch.setattr(channel, "is_connected", lambda h: e.connected)
    monkeypatch.setattr(channel, "send_command",
                        lambda h, c, timeout=60: e.sent.append(c) or {"ok": True, "output": "", "error": ""})
    monkeypatch.setattr(operations, "_spawn", lambda fn, *a: fn(*a))

    def evaluate_all(*a, **k):
        fresh = "fresh" if e.node_fresh else "stale"
        out = {h: st.SubjectStatus(h, "host", e.host_state, list(e.host_flags),
                                   [{"source": "node", "freshness": fresh}]) for h in ("h1", "h2")}
        out.update({s: st.SubjectStatus(s, "service", e.svc_state) for s in ("web", "app", "dry", "base")})
        return out

    monkeypatch.setattr(st, "evaluate_all", evaluate_all)
    return e


def incident(subject="web", kind="service_down", status="open"):
    with store._conn() as c:
        return incidents.fmt_id(c.execute(
            "INSERT INTO incidents (subject, kind, severity, status, detected_at) VALUES (?,?,?,?,?)",
            (subject, kind, "warning", status, datetime.now().isoformat(timespec="seconds"))).lastrowid)


def log_rows():
    with store._conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM action_log ORDER BY id")]


def test_auto_restart_once_and_success_note(env):
    iid = incident()
    assert autoheal.process(iid) == "restarted"
    assert [c["unit"] for c in env.sent] == ["nginx"]
    assert env.notes[0].startswith("自動再起動します")
    assert log_rows()[0]["requested_by"] == "autoheal" and log_rows()[0]["verification"] == "ok"
    with store._conn() as c:
        assert any("自動再起動が成功" in r[0] for r in c.execute("SELECT note FROM incident_notes"))
    # 同じ Incident の再オープンなど 2 回目の通知では再実行しない（無言）
    assert autoheal.process(iid).startswith("ignored") and len(env.sent) == 1 and len(env.notes) == 1


def test_rate_limit_3_per_24h_notifies_once(env):
    for _ in range(3):
        assert autoheal.process(incident()) == "restarted"
    n = len(env.notes)
    iid = incident()
    assert autoheal.process(iid).startswith("skipped") and len(env.sent) == 3
    assert len(env.notes) == n + 1 and "上限" in env.notes[-1]
    autoheal.process(iid)
    assert len(env.notes) == n + 1  # Incident あたり 1 回
    with store._conn() as c:  # 24 時間より前の分は数えない
        c.execute("UPDATE action_log SET started_at=?", ((datetime.now() - timedelta(hours=25)).isoformat(),))
    assert autoheal.process(incident()) == "restarted"


def test_dependency_incident_skips_and_notifies(env):
    incident("base")
    assert autoheal.process(incident("app")).startswith("skipped")
    assert not env.sent and "依存先 base" in env.notes[-1]


def test_dependency_host_incident_skips(env):
    incident("h2", "host_lost")
    assert autoheal.process(incident("app")).startswith("skipped") and not env.sent


@pytest.mark.parametrize("field,value", [("host_state", "unhealthy"), ("host_state", "unknown"),
                                         ("host_flags", ["node_lost"]), ("node_fresh", False),
                                         ("connected", False)])
def test_host_or_node_lost_skips_and_notifies(env, field, value):
    setattr(env, field, value)
    assert autoheal.process(incident()).startswith("skipped")
    assert not env.sent and len(env.notes) == 1 and "Host h1" in env.notes[0]


def test_dry_run_notices_without_sending(env):
    iid = incident("dry")
    assert autoheal.process(iid) == "dry_run"
    assert not env.sent and env.notes == [f"自動再起動するはずだった: dry（{iid}）"]
    assert log_rows()[0]["decision"] == "dry_run"
    assert autoheal.process(iid).startswith("ignored") and len(env.notes) == 1
    for _ in range(5):  # dry-run は回数に数えない
        assert autoheal.process(incident("dry")) == "dry_run"


def test_switch_off_even_for_queued_item(env):
    iid = incident()
    autoheal.enqueue(iid)  # 待機中に off にする
    autoheal.set_enabled(False)
    assert autoheal.is_enabled() is False
    assert autoheal.process(autoheal._q.get_nowait()).startswith("skipped")
    assert not env.sent and "停止スイッチ" in env.notes[-1]
    autoheal.set_enabled(True)
    assert autoheal.process(incident()) == "restarted"


def test_verification_failure_stops_and_notifies(env):
    env.svc_state = "unhealthy"
    iid = incident()
    assert autoheal.process(iid) == "restarted"
    assert "回復しませんでした" in env.notes[-1] and "承認" in env.notes[-1]
    assert autoheal.process(iid).startswith("ignored") and len(env.sent) == 1  # 再試行しない


def test_undeclared_and_wrong_kind_are_silent(env):
    for subject, kind in (("appr", "service_down"), ("bare", "service_down"), ("web", "service_degraded"),
                          ("h1", "host_lost")):
        assert autoheal.process(incident(subject, kind)).startswith("ignored")
    assert not env.sent and not env.notes


def test_resolved_incident_ignored(env):
    assert autoheal.process(incident(status="resolved")).startswith("ignored") and not env.sent


# ---- 故障注入: Core のチャネル・Node daemon・状態判定・Event・Incident は実物、systemctl だけ模擬 ----

def test_fault_injection_end_to_end(base, monkeypatch):
    state = {"web": "running"}

    def runner(argv, **k):
        if argv[:2] == ["systemctl", "restart"]:
            state["web"] = "running"  # 再起動で failed -> running
            feed()  # 次の telemetry を待たず同期で反映（バックグラウンドの feeder は負荷で遅れて検証窓に間に合わない）
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def feed():  # Node の telemetry の代わり
        store.put_observation("h1", "node", {"services": [{"id": "web", "state": state["web"]}],
                                             "resources": {}, "disks": []})

    monkeypatch.setattr(channel, "REPORT_INTERVAL_SEC", 0.05)
    monkeypatch.setattr(events, "_subscribers", [incidents.handle])
    monkeypatch.setattr(incidents, "_created_hooks", [lambda i, r: outcomes.append(autoheal.process(i))])  # worker の代わりに同期で呼ぶ
    outcomes = []
    verified = threading.Event()
    real_verify = operations._verify

    def verify(*a):
        try:
            real_verify(*a)
        finally:
            verified.set()

    monkeypatch.setattr(operations, "_verify", verify)
    channel._connections.clear()
    token = store.issue_token("h1")
    ex = Executor("h1", frozenset({"nginx"}), frozenset(), runner)
    result = {}

    def body():
        feed()
        events.update(st.evaluate_all())  # 基準状態: healthy
        state["web"] = "failed"  # 故障注入
        feed()  # 同期で反映する。別スレッドの feeder だと負荷で遅れ、failed を見ずに Incident が作られない
        events.update(st.evaluate_all())
        events.update(st.evaluate_all())  # 2 回連続で確定 -> service_down -> Incident -> autoheal
        assert verified.wait(30), outcomes  # 検証スレッドの完了を待つ（時間依存の sleep ではなく完了通知）
        events.update(st.evaluate_all())
        events.update(st.evaluate_all())  # healthy が 2 回 -> recovered -> 自動解決
        result["rows"] = log_rows()

    async def main():
        async with channel.make_server("127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            task = asyncio.create_task(daemon.run(f"ws://127.0.0.1:{port}", "h1", token, executor=ex))
            for _ in range(600):  # 負荷時でも接続完了を待つ（待たずに進むと Node 未接続で見送られる）
                if channel.is_connected("h1"):
                    break
                await asyncio.sleep(0.05)
            assert channel.is_connected("h1")
            try:
                await asyncio.to_thread(body)
            finally:
                task.cancel()

    asyncio.run(main())
    rows = result["rows"]
    assert len(rows) == 1 and rows[0]["requested_by"] == "autoheal" and rows[0]["ok"] == 1
    assert rows[0]["verification"] == "ok"
    with store._conn() as c:
        inc = c.execute("SELECT * FROM incidents").fetchall()
    assert len(inc) == 1 and inc[0]["status"] == "resolved" and inc[0]["resolved_by"] == "auto"
    assert any(n.startswith("自動再起動します") for n in base)
