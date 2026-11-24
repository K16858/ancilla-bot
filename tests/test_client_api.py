import argparse
import json
import threading
import time
from datetime import datetime

import httpx
import pytest

from ancilla_bot.api import server
from ancilla_bot.cli.commands.api import cmd_api
from ancilla_bot.cli.health import check_bind_hosts
from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import incidents as I
from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store

YAML = """
hosts:
  - {id: a, name: A, os: ubuntu, criticality: high, node: true}
services:
  - {id: web, name: Web, host: a, kind: docker, depends_on: [dbs]}
  - {id: dbs, name: DB, host: a, kind: systemd}
"""


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    p = tmp_path / "h.yaml"
    p.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("ANCILLA_HOMELAB_PATH", str(p))
    monkeypatch.setattr(inv, "_cache", None)
    monkeypatch.setattr(I, "append_notification", lambda **k: None)
    monkeypatch.setattr(I, "_created_hooks", [])
    monkeypatch.setattr(server, "SSE_POLL_SEC", 0.05)
    srv = server.make_server("127.0.0.1", 0, lambda m, i: f"echo:{m}")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def add_event(subject="dbs", kind="service_down"):
    with store._conn() as c:
        return c.execute(
            "INSERT INTO events (subject, kind, from_state, to_state, detected_at, evidence) "
            "VALUES (?, ?, 'healthy', 'unhealthy', ?, '[]')",
            (subject, kind, datetime.now().isoformat(timespec="seconds")),
        ).lastrowid


def add_incident(subject="dbs"):
    eid = add_event(subject)
    I.handle({"id": eid, "subject": subject, "kind": "service_down", "from": "healthy", "to": "unhealthy",
              "flags": [], "detected_at": datetime.now().isoformat(timespec="seconds"), "evidence": []})


def sse(url, token, headers=None, n=1, timeout=5, on_connected=None):
    """data 行を持つブロックを n 個集めて返す。"""
    out, block = [], []
    triggered = False
    with httpx.stream("GET", url, headers=auth(token) | (headers or {}), timeout=timeout) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line == "":
                if any(b.startswith("data:") for b in block):
                    out.append(block)
                elif on_connected is not None and not triggered and ": connected" in block:
                    triggered = True
                    threading.Thread(target=on_connected, daemon=True).start()
                block = []
                if len(out) >= n:
                    break
            else:
                block.append(line)
    return out


def test_401_and_403(api):
    r = store.create_api_token("r", "read")
    o = store.create_api_token("o", "operate")
    assert httpx.get(f"{api}/api/v1/summary").status_code == 401
    assert httpx.get(f"{api}/api/v1/summary", headers=auth("nope")).status_code == 401
    assert httpx.get(f"{api}/api/v1/summary", headers=auth(r)).status_code == 200
    assert httpx.get(f"{api}/api/v1/summary", headers=auth(o)).status_code == 200  # operate は read を含む
    assert httpx.post(f"{api}/api/v1/chat", json={"message": "hi"}, headers=auth(r)).status_code == 403
    res = httpx.post(f"{api}/api/v1/chat", json={"message": "hi"}, headers=auth(o))
    assert res.json() == {"response": "echo:hi"}
    assert store.revoke_api_token("o")
    assert httpx.get(f"{api}/api/v1/summary", headers=auth(o)).status_code == 401
    assert httpx.post(f"{api}/api/v1/chat", json={"message": "hi"}).status_code == 401


def test_rotation_revokes_old_token(api):
    old = store.create_api_token("x", "read")
    new = store.create_api_token("x", "read")
    assert httpx.get(f"{api}/api/v1/nodes", headers=auth(old)).status_code == 401
    assert httpx.get(f"{api}/api/v1/nodes", headers=auth(new)).status_code == 200


def test_read_endpoints(api):
    t = store.create_api_token("r", "read")
    store.issue_token("a")
    store.touch("a", os="ubuntu", version="1.0", hostname="h")
    add_incident("dbs")

    def get(path):
        r = httpx.get(f"{api}/api/v1{path}", headers=auth(t))
        return r.status_code, r.json()

    code, s = get("/summary")
    assert code == 200 and s["open_incidents"] == {"warning": 1} and s["evaluated_at"]
    assert sum(s["hosts"].values()) == 1 and sum(s["services"].values()) == 2
    code, hosts = get("/hosts")
    assert hosts[0]["id"] == "a" and hosts[0]["status"]["state"] and hosts[0]["evaluated_at"]
    code, h = get("/hosts/a")
    assert h["services"] == ["web", "dbs"]
    assert get("/hosts/zzz")[0] == 404
    assert [x["id"] for x in get("/services")[1]] == ["web", "dbs"]
    code, sv = get("/services/dbs")
    assert sv["impact"]["dependents"] == ["web"] and "evidence" in sv["status"]
    code, nodes = get("/nodes")
    assert nodes[0]["host_id"] == "a" and nodes[0]["os"] == "ubuntu" and nodes[0]["last_seen"]
    assert "token_hash" not in nodes[0]
    assert len(get("/incidents")[1]) == 1
    code, d = get("/incidents/INC-000001")
    assert d["subject"] == "dbs" and d["events"]
    assert get("/incidents/INC-000099")[0] == 404
    code, evs = get("/events?subject=dbs&limit=5")
    assert len(evs) == 1 and evs[0]["detected_at"]
    assert get("/events?since=bogus")[0] == 400
    assert get("/nope")[0] == 404


def test_sse_new_events_and_catch_up(api):
    t = store.create_api_token("r", "read")
    first = add_event()
    second = add_event("web")
    # Last-Event-ID から追い付く（first は来ず second が来る）
    got = sse(f"{api}/api/v1/stream", t, {"Last-Event-ID": str(first)})
    assert got[0][0] == f"id: {second}" and got[0][1] == "event: homelab_event"
    assert json.loads(got[0][2][len("data: "):])["subject"] == "web"
    # ?after= でも同じ
    assert sse(f"{api}/api/v1/stream?after={first}", t)[0][0] == f"id: {second}"
    # ID 無しは接続後の新規だけ
    got = sse(f"{api}/api/v1/stream", t, on_connected=add_event)
    assert got[0][0] != f"id: {second}" and got[0][1] == "event: homelab_event"


def test_sse_incidents_changed(api):
    t = store.create_api_token("r", "read")
    add_incident()
    got = sse(f"{api}/api/v1/stream", t, on_connected=lambda: I.acknowledge("INC-000001"))
    assert got[0][0] == "event: incidents_changed"


def test_stream_does_not_block_other_requests(api):
    t = store.create_api_token("r", "read")
    with httpx.stream("GET", f"{api}/api/v1/stream", headers=auth(t)) as r:
        next(r.iter_lines())
        assert httpx.get(f"{api}/health").status_code == 200


def test_legacy_gating(api, monkeypatch):
    assert httpx.get(f"{api}/health").status_code == 200  # ループバック
    monkeypatch.setattr(server, "_peer", lambda h: "192.168.1.9")
    assert httpx.get(f"{api}/health").json() == {"ok": True}  # 死活監視用に開放
    assert httpx.get(f"{api}/chat").status_code == 403
    assert httpx.post(f"{api}/chat", json={"message": "hi"}).status_code == 403
    r = store.create_api_token("r", "read")
    o = store.create_api_token("o", "operate")
    assert httpx.get(f"{api}/chat", headers=auth(r)).status_code == 403
    assert httpx.get(f"{api}/chat", headers=auth(o)).status_code == 404  # 認証は通る（GET /chat は無い）
    assert httpx.post(f"{api}/chat", json={"message": "hi"}, headers=auth(o)).json() == {"response": "echo:hi"}
    assert httpx.get(f"{api}/chat", headers=auth("bad")).status_code == 401


def test_bind_guard_keeps_ws_and_mcp(monkeypatch):
    monkeypatch.delenv("ANCILLA_INSECURE_BIND", raising=False)
    check_bind_hosts({"MCP_HTTP": "127.0.0.1", "WS": "127.0.0.1"})  # API はガード対象に含めない
    for name in ("WS", "MCP_HTTP"):
        with pytest.raises(SystemExit):
            check_bind_hosts({name: "0.0.0.0"})


def test_token_cli(api, capsys):
    ns = lambda **k: argparse.Namespace(**k)  # noqa: E731
    assert cmd_api(ns(token_command="create", name="webui", role="read")) == 0
    token = capsys.readouterr().out.strip()
    assert store.verify_api_token(token) == "read"
    cmd_api(ns(token_command="list"))
    out = capsys.readouterr().out
    assert "webui" in out and token not in out
    assert cmd_api(ns(token_command="revoke", name="webui")) == 0
    assert store.verify_api_token(token) is None
    assert cmd_api(ns(token_command="revoke", name="webui")) == 1


# ---- 承認 API ----

def _pending(run_id: str, source: str = "user", tool: str = "demo__write", args=None):
    from ancilla_bot.runtime.approval import save_pending_approval

    db.create_agent_run(run_id, source=source, user_input="x")
    step_id = db.create_agent_run_step(run_id, turn_index=0, status="approval_pending", action=tool,
                                       action_input={})
    save_pending_approval(run_id=run_id, tool_name=tool, args=args or {}, turn_index=0, step_id=step_id,
                          messages=[{"role": "user", "content": "x"}], source=source)


@pytest.fixture
def tool(monkeypatch):
    from ancilla_bot.tools import registry

    calls = []
    monkeypatch.setitem(registry.TOOL_REGISTRY, "demo__write", lambda **kw: calls.append(kw) or "wrote")
    monkeypatch.setattr("ancilla_bot.core.agent_loop._agent_loop_turns", lambda **kw: ("resumed", None))
    return calls


def post(url, token, path):
    return httpx.post(f"{url}/api/v1/approvals/{path}", headers=auth(token), timeout=10)


def test_approval_list_me_and_read_forbidden(api, tool):
    _pending("r1", args={"x": 1})
    r = store.create_api_token("viewer", "read")
    assert httpx.get(f"{api}/api/v1/me", headers=auth(r)).json() == {"name": "viewer", "role": "read"}
    [a] = httpx.get(f"{api}/api/v1/approvals", headers=auth(r)).json()
    assert (a["run_id"], a["tool"], a["args"], a["source"]) == ("r1", "demo__write", {"x": 1}, "user")
    assert a["expires_at"] > a["created_at"]
    assert post(api, r, "r1/approve").status_code == 403
    assert post(api, r, "r1/reject").status_code == 403
    assert tool == [] and db.get_pending_approval("r1")


def test_operate_approve_records_approver(api, tool):
    _pending("r1")
    o = store.create_api_token("ui", "operate")
    out = post(api, o, "r1/approve")
    assert out.status_code == 200 and "resumed" in out.json()["message"]
    assert len(tool) == 1 and db.get_agent_run("r1")["status"] != "awaiting_approval"
    with db._conn() as c:
        assert c.execute("SELECT status, resolved_by FROM pending_approvals").fetchone() == ("approved", "webui:ui")


def test_operate_reject(api, tool):
    _pending("r1")
    o = store.create_api_token("ui", "operate")
    assert "Rejected" in post(api, o, "r1/reject").json()["message"]
    assert tool == [] and db.get_agent_run("r1")["status"] == "cancelled"


def test_expired_and_policy_deny_via_api(api, tool, monkeypatch):
    o = store.create_api_token("ui", "operate")
    _pending("old")
    monkeypatch.setenv("ANCILLA_APPROVAL_TTL_HOURS", "-1")
    assert "expired" in post(api, o, "old/approve").json()["message"]
    monkeypatch.delenv("ANCILLA_APPROVAL_TTL_HOURS")
    _pending("deny", source="heartbeat")  # 自律実行元の外部書き込みは承認時にも DENY
    assert "denied" in post(api, o, "deny/approve").json()["message"]
    assert tool == [] and db.get_agent_run("deny")["status"] == "failed"


def test_double_approve_executes_once(api, tool, monkeypatch):
    import time as _t
    from ancilla_bot.tools import registry

    monkeypatch.setitem(registry.TOOL_REGISTRY, "demo__write", lambda **kw: _t.sleep(0.3) or tool.append(kw) or "ok")
    _pending("r1")
    o = store.create_api_token("ui", "operate")
    res = []
    ts = [threading.Thread(target=lambda: res.append(post(api, o, "r1/approve").json()["message"])) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(tool) == 1
    assert sum("resumed" in m for m in res) == 1


def test_sse_approvals_changed(api, tool):
    t = store.create_api_token("r", "read")
    assert sse(f"{api}/api/v1/stream", t, on_connected=lambda: _pending("r1"))[0][0] == "event: approvals_changed"


# ---- タイマー & 通知 API ----

def test_timers_crud_and_permissions(api):
    r = store.create_api_token("reader", "read")
    o = store.create_api_token("op", "operate")

    assert httpx.get(f"{api}/api/v1/timers").status_code == 401
    assert httpx.get(f"{api}/api/v1/timers", headers=auth(r)).status_code == 200
    assert httpx.post(f"{api}/api/v1/timers", json={"duration_sec": 60}, headers=auth(r)).status_code == 403
    assert httpx.patch(f"{api}/api/v1/timers/TMR-0001", json={"label": "x"}, headers=auth(r)).status_code == 403
    assert httpx.delete(f"{api}/api/v1/timers/TMR-0001", headers=auth(r)).status_code == 403

    assert httpx.post(f"{api}/api/v1/timers", json={}, headers=auth(o)).status_code == 400
    assert httpx.post(f"{api}/api/v1/timers", json={"duration_sec": 0}, headers=auth(o)).status_code == 400
    assert httpx.post(f"{api}/api/v1/timers", content=b"{bad", headers=auth(o)).status_code == 400

    res = httpx.post(f"{api}/api/v1/timers", json={"duration_sec": 180, "label": "パスタ"}, headers=auth(o))
    assert res.status_code == 201
    t1 = res.json()
    assert t1["id"] == "TMR-0001"
    assert t1["source"] == "api:op"
    assert t1["label"] == "パスタ"

    listed = httpx.get(f"{api}/api/v1/timers", headers=auth(r)).json()
    assert listed["server_now"] and len(listed["timers"]) == 1
    assert httpx.get(f"{api}/api/v1/timers/TMR-0001", headers=auth(r)).json()["id"] == "TMR-0001"
    assert httpx.get(f"{api}/api/v1/timers/TMR-9999", headers=auth(r)).status_code == 404

    upd = httpx.patch(
        f"{api}/api/v1/timers/TMR-0001",
        json={"add_sec": 60, "label": "うどん"},
        headers=auth(o),
    )
    assert upd.status_code == 200 and upd.json()["duration_sec"] == 240 and upd.json()["label"] == "うどん"
    assert httpx.patch(f"{api}/api/v1/timers/TMR-9999", json={"label": "x"}, headers=auth(o)).status_code == 404
    assert httpx.patch(f"{api}/api/v1/timers/TMR-0001", json={"action": "stop"}, headers=auth(o)).status_code == 400

    from ancilla_bot.assistant import timers

    with timers._conn() as c:
        c.execute("UPDATE timers SET status='firing', fired_at=created_at WHERE id=1")
    stopped = httpx.patch(f"{api}/api/v1/timers/TMR-0001", json={"action": "stop"}, headers=auth(o))
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    assert httpx.get(f"{api}/api/v1/timers", headers=auth(r)).json()["timers"] == []
    assert len(httpx.get(f"{api}/api/v1/timers?all=1", headers=auth(r)).json()["timers"]) == 1

    t2 = httpx.post(f"{api}/api/v1/timers", json={"duration_sec": 90}, headers=auth(o)).json()
    deleted = httpx.delete(f"{api}/api/v1/timers/{t2['id']}", headers=auth(o))
    assert deleted.status_code == 200 and deleted.json()["status"] == "cancelled"
    assert httpx.delete(f"{api}/api/v1/timers/TMR-9999", headers=auth(o)).status_code == 404


def test_timers_and_notifications_work_without_homelab_yaml(api, monkeypatch, tmp_path):
    r = store.create_api_token("reader", "read")
    monkeypatch.setenv("ANCILLA_HOMELAB_PATH", str(tmp_path / "missing.yaml"))
    assert httpx.get(f"{api}/api/v1/summary", headers=auth(r)).status_code == 503
    assert httpx.get(f"{api}/api/v1/timers", headers=auth(r)).status_code == 200
    assert httpx.get(f"{api}/api/v1/notifications", headers=auth(r)).status_code == 200


def test_notifications_endpoint(api):
    from ancilla_bot.notifications.store import append_notification, append_report

    r = store.create_api_token("reader", "read")
    assert httpx.get(f"{api}/api/v1/notifications").status_code == 401

    id1 = append_notification("node down", level="critical", title="INC-000001", category="incident")
    id2 = append_report("daily", "all green")

    all_rows = httpx.get(f"{api}/api/v1/notifications", headers=auth(r))
    assert all_rows.status_code == 200
    assert [x["id"] for x in all_rows.json()] == [id2, id1]

    since_rows = httpx.get(f"{api}/api/v1/notifications?since_id={id1}&limit=10", headers=auth(r))
    assert since_rows.status_code == 200
    assert [x["id"] for x in since_rows.json()] == [id2]
    assert httpx.get(f"{api}/api/v1/notifications?since_id=bad", headers=auth(r)).status_code == 400
