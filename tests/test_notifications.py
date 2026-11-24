import json
from pathlib import Path

import pytest

from ancilla_bot.notifications import store
from ancilla_bot.notifications.pending_take import take_pending_jsonl_lines
from ancilla_bot.notifications.store import append_notification, append_report


@pytest.fixture(autouse=True)
def _clean_hooks():
    store.clear_notification_hooks()
    yield
    store.clear_notification_hooks()


def test_append_notification_writes_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_NOTIFICATIONS_DIR", str(tmp_path))
    append_notification("hello", source="system", title="t", detail="d")
    line = (tmp_path / "pending.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["message"] == "hello"
    assert rec["source"] == "system"
    assert rec["title"] == "t"
    assert rec["detail"] == "d"


def test_append_report_sets_source(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_NOTIFICATIONS_DIR", str(tmp_path))
    append_report("title", "body")
    rec = json.loads((tmp_path / "pending.jsonl").read_text(encoding="utf-8"))
    assert rec["source"] == "report"
    assert rec["title"] == "title"
    assert rec["message"] == "body"
    assert "detail" not in rec


def test_notification_events_persisted_across_pending_take(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_NOTIFICATIONS_DIR", str(tmp_path))
    assert store.last_notification_id() == 0

    id1 = append_notification(
        "service down",
        source="system",
        level="critical",
        title="INC-000001",
        category="incident",
    )
    id2 = append_report("daily", "summary body")
    assert id2 > id1
    assert store.last_notification_id() == id2

    # Discord / Slack 相当で pending.jsonl を消費しても SQLite 配信ログは残る
    taken = take_pending_jsonl_lines(tmp_path / "pending.jsonl")
    assert len(taken) == 2
    assert not (tmp_path / "pending.jsonl").exists()

    recent = store.list_notifications(limit=10)
    assert [r["id"] for r in recent] == [id2, id1]
    assert recent[0]["category"] == "report"
    assert recent[1]["category"] == "incident"
    assert recent[1]["level"] == "critical"

    after = store.list_notifications(since_id=id1, limit=10)
    assert [r["id"] for r in after] == [id2]
    assert store.notifications_after(0) == [recent[1], recent[0]]


def test_notification_hooks(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_NOTIFICATIONS_DIR", str(tmp_path))
    seen = []

    def cb(ev):
        seen.append(ev)

    store.subscribe_notifications(lambda _ev: (_ for _ in ()).throw(RuntimeError("boom")))
    store.subscribe_notifications(cb)
    store.subscribe_notifications(cb)  # 重複登録されない

    eid = append_notification("ping", category="timer", title="TMR-0001")
    assert len(seen) == 1
    assert seen[0]["id"] == eid
    assert seen[0]["category"] == "timer"
    assert seen[0]["title"] == "TMR-0001"
