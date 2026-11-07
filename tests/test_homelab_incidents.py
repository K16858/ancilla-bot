import json
from datetime import datetime, timedelta

import pytest

from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import incidents as I
from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store

T0 = datetime(2026, 11, 7, 12, 0, 0)
YAML = """
hosts:
  - {id: a, name: A, os: ubuntu, criticality: high, node: true}
  - {id: b, name: B, os: ubuntu, node: true}
services:
  - {id: web, name: Web, host: a, kind: docker, criticality: high, depends_on: [dbs]}
  - {id: dbs, name: DB, host: a, kind: systemd}
  - {id: app, name: App, host: b, kind: systemd, depends_on: [dbs]}
"""


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    p = tmp_path / "h.yaml"
    p.write_text(YAML, encoding="utf-8")
    monkeypatch.setenv("ANCILLA_HOMELAB_PATH", str(p))
    monkeypatch.setattr(inv, "_cache", None)
    sent = []
    monkeypatch.setattr(I, "append_notification", lambda **k: sent.append(k))
    monkeypatch.setattr(I, "_created_hooks", [])
    return sent


_n = [0]


def ev(subject, kind, to="unhealthy", minutes=0):
    _n[0] += 1
    t = (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with store._conn() as c:  # incident_events は実在する events 行を結ぶ
        eid = c.execute("INSERT INTO events (subject, kind, from_state, to_state, detected_at, evidence) "
                        "VALUES (?, ?, 'healthy', ?, ?, '[]')", (subject, kind, to, t)).lastrowid
    return {"id": eid, "subject": subject, "kind": kind, "from": "healthy", "to": to, "flags": [],
            "detected_at": t, "evidence": []}


def incs(all_=True):
    return json.loads(I.homelab_list_incidents(all=all_))


def test_three_scenarios_one_incident_each(env):
    I.handle(ev("dbs", "service_down"))
    I.handle(ev("a", "disk_pressure", "degraded"))
    I.handle(ev("b", "node_lost", "unknown"))
    assert [(x["subject"], x["severity"]) for x in incs()] == [("b", "warning"), ("a", "warning"), ("dbs", "warning")]
    assert len(env) == 3 and env[0]["level"] == "warning"


def test_critical_and_impact_and_severity_up(env):
    I.handle(ev("dbs", "service_degraded", "degraded"))
    I.handle(ev("dbs", "service_down"))  # 同じ主体: 追加。warning のまま通知なし
    assert len(env) == 1 and len(incs()) == 1
    I.handle(ev("web", "service_down"))  # 依存先 dbs の Incident へ
    assert len(incs()) == 1
    d = json.loads(I.homelab_get_incident("INC-000001"))
    assert [e["role"] for e in d["events"]] == ["own", "own", "impact"]
    assert set(d["affected_services"]) == {"web", "app"} and len(env) == 1
    I.handle(ev("a", "disk_pressure", "degraded"))
    I.handle(ev("a", "host_lost", "unhealthy"))  # warning -> critical (criticality high)
    assert env[-1]["level"] == "critical" and "深刻度上昇" in env[-1]["message"] and len(env) == 3


def test_critical_on_create(env):
    I.handle(ev("web", "service_down"))
    assert env[0]["level"] == "critical" and "Web" in env[0]["message"]


def test_host_priority_no_service_incidents(env):
    I.handle(ev("a", "host_lost", "unknown"))
    I.handle(ev("web", "service_down"))
    I.handle(ev("dbs", "service_down"))
    [x] = incs()
    assert x["subject"] == "a" and len(env) == 1
    assert [e["role"] for e in json.loads(I.homelab_get_incident(x["id"]))["events"]] == ["own", "host", "host"]
    I.handle(ev("app", "service_down"))  # b 上だが dbs(a) に依存: a の Host Incident へ
    assert len(incs()) == 1


def test_auto_resolve_reopen_within_hour_and_new_after(env):
    I.handle(ev("dbs", "service_down", minutes=0))
    I.handle(ev("dbs", "recovered", "healthy", minutes=10))
    [x] = incs()
    assert x["status"] == "resolved" and x["resolved_by"] == "auto" and "10分" in env[-1]["message"]
    I.handle(ev("web", "recovered", "healthy", minutes=11))  # Incident 無し: 無視
    assert len(env) == 2
    I.handle(ev("dbs", "service_down", minutes=60))  # 解決(10分)から50分: 再オープン
    [x] = incs()
    assert x["status"] == "open" and x["resolved_by"] is None and "再オープン" in env[-1]["message"]
    I.handle(ev("dbs", "recovered", "healthy", minutes=70))
    I.handle(ev("dbs", "service_down", minutes=131))  # 61分後: 新規
    assert [x["id"] for x in incs()] == ["INC-000002", "INC-000001"]
    I.handle(ev("dbs", "recovered", "healthy", minutes=140))
    I.handle(ev("dbs", "service_degraded", "degraded", minutes=150))  # kind 違い: 新規
    assert len(incs()) == 3


def test_notifications_and_diagnosis_hook(env):
    hooks = []
    I.subscribe_created(lambda i, r: hooks.append((i, r)))
    I.handle(ev("dbs", "service_down"))
    I.handle(ev("dbs", "service_down"))
    assert hooks == [("INC-000001", False)] and len(env) == 1
    assert I.set_diagnosis("INC-000001", "原因: OOM") and "診断完了" in env[-1]["message"]
    assert I.set_diagnosis("INC-000009", "x") is False
    d = json.loads(I.homelab_get_incident("INC-000001"))
    assert d["diagnosis"] == "原因: OOM" and d["diagnosis_status"] == "done"
    assert I.acknowledge("INC-000001").endswith("確認済みにしました") and len(env) == 2
    assert incs(False)[0]["status"] == "acknowledged"
    assert "解決しました" in I.resolve("INC-000001") and len(env) == 3
    assert incs()[0]["resolved_by"] == "manual" and incs(False) == []
    assert I.resolve("INC-000001").startswith("Error") and I.homelab_get_incident("INC-9").startswith("Error")
