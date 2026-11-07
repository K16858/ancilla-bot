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


def sse(url, token, headers=None, n=1, timeout=5):
    """data 行を持つブロックを n 個集めて返す。"""
    out, block = [], []
    with httpx.stream("GET", url, headers=auth(token) | (headers or {}), timeout=timeout) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line == "":
                if any(b.startswith("data:") for b in block):
                    out.append(block)
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
    threading.Timer(0.5, add_event).start()
    got = sse(f"{api}/api/v1/stream", t)
    assert got[0][0] != f"id: {second}" and got[0][1] == "event: homelab_event"


def test_sse_incidents_changed(api):
    t = store.create_api_token("r", "read")
    add_incident()
    threading.Timer(0.5, lambda: I.acknowledge("INC-000001")).start()  # 別プロセスの CLI 相当
    got = sse(f"{api}/api/v1/stream", t)
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
