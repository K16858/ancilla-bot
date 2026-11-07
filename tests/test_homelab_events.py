import json
from datetime import datetime, timedelta

import pytest

from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import events
from ancilla_bot.homelab import status as st

T0 = datetime(2026, 11, 7, 12, 0, 0)


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setattr(events, "_subscribers", [])


def svc(state, id_="web"):
    return {id_: st.SubjectStatus(id_, "service", state, [], [{"source": "node", "freshness": "fresh"}])}


def host(state, flags=(), node="fresh", id_="host1"):
    ev = [{"source": "node", "freshness": node, "observed_at": None, "values": None}]
    return {id_: st.SubjectStatus(id_, "host", state, list(flags), ev)}


class Clock:
    def __init__(self):
        self.t = T0

    def run(self, statuses):
        self.t += timedelta(seconds=30)
        return events.update(statuses, self.t)


def test_first_observation_no_event():
    assert Clock().run(svc("unhealthy")) == []
    assert events.homelab_get_events() == "[]"


def test_blip_ignored_two_in_a_row_confirms_and_recovers():
    c = Clock()
    c.run(svc("healthy"))
    assert c.run(svc("unhealthy")) == []
    assert c.run(svc("healthy")) == []  # 揺らぎ: 確認待ちが消える
    assert c.run(svc("unhealthy")) == []
    [e] = c.run(svc("unhealthy"))
    assert (e["kind"], e["from"], e["to"], e["subject"]) == ("service_down", "healthy", "unhealthy", "web")
    assert c.run(svc("unhealthy")) == []  # 同じ状態では再発行しない
    assert c.run(svc("healthy")) == []
    [r] = c.run(svc("healthy"))
    assert (r["kind"], r["from"], r["to"]) == ("recovered", "unhealthy", "healthy")


def test_service_kinds_and_unknown():
    c = Clock()
    c.run(svc("healthy"))
    c.run(svc("degraded"))
    assert c.run(svc("degraded"))[0]["kind"] == "service_degraded"
    c.run(svc("unknown"))
    assert c.run(svc("unknown")) == []
    c.run(svc("healthy"))
    assert c.run(svc("healthy")) == []  # unknown からの復帰は Event なし


def test_host_scenarios():
    c = Clock()
    c.run(host("healthy"))
    # ディスク逼迫
    c.run(host("degraded"))
    assert c.run(host("degraded"))[0]["kind"] == "disk_pressure"
    c.run(host("unhealthy"))
    assert c.run(host("unhealthy"))[0]["kind"] == "disk_pressure"
    c.run(host("healthy"))
    assert c.run(host("healthy"))[0]["kind"] == "recovered"
    # Node だけ停止
    lost = host("degraded", ["node_lost"], node="stale")
    c.run(lost)
    assert c.run(lost)[0]["kind"] == "node_lost"
    c.run(host("healthy"))
    assert c.run(host("healthy"))[0]["kind"] == "recovered"
    # ホスト途絶: ヘルスチェック全滅 -> unhealthy / 手掛かり無し -> unknown
    down = host("unhealthy", node="stale")
    c.run(down)
    assert c.run(down)[0]["kind"] == "host_lost"
    c.run(host("healthy"))
    c.run(host("healthy"))
    unk = host("unknown", node="stale")
    c.run(unk)
    assert c.run(unk)[0]["kind"] == "host_lost"
    # unhealthy(途絶) -> unknown は追加 Event なし
    c.run(down)
    c.run(down)
    c.run(unk)
    assert c.run(unk) == []


def test_subscriber_called_once_per_event_after_save():
    got = []
    events.subscribe(lambda e: got.append((e["id"], json.loads(events.homelab_get_events())[0]["id"])))
    events.subscribe(lambda e: 1 / 0)  # 失敗しても他へ影響しない
    c = Clock()
    c.run(svc("healthy"))
    c.run(svc("unhealthy"))
    c.run(svc("unhealthy"))
    c.run(svc("unhealthy"))
    assert got == [(1, 1)]


def test_get_events_filters():
    c = Clock()
    for s in ("healthy",):
        c.run(svc(s) | svc(s, "db"))
    for _ in range(2):
        c.run(svc("unhealthy") | svc("unhealthy", "db"))
    for _ in range(2):
        c.run(svc("healthy"))
    all_ = json.loads(events.homelab_get_events())
    assert [e["id"] for e in all_] == [3, 2, 1]  # 新しい順
    assert {e["subject"] for e in json.loads(events.homelab_get_events("db"))} == {"db"}
    assert len(json.loads(events.homelab_get_events(limit=1))) == 1
    assert len(json.loads(events.homelab_get_events(since=(T0 + timedelta(hours=1)).isoformat()))) == 0
    assert not events.homelab_get_events(since="1d").startswith("Error")  # 相対指定は実時刻基準
    assert events.homelab_get_events(since="xx").startswith("Error")


def test_startup_grace_skips_process(monkeypatch):
    import time

    called = []
    monkeypatch.setattr(st, "evaluate_all", lambda *a, **k: called.append(1) or {})
    monkeypatch.setattr(events, "_started", time.monotonic())
    assert events.process(interval=30) == [] and not called
    monkeypatch.setattr(events, "_started", time.monotonic() - 91)
    events.process(interval=30)
    assert called
