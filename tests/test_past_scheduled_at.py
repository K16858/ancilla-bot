from datetime import datetime, timedelta
from pathlib import Path

from ancilla_bot.heartbeat import db


def test_insert_rejects_past_scheduled_at(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    past = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    result = db.manage_state(
        "reminders",
        "insert",
        {"content": "学割証明書", "scheduled_at": past},
    )
    assert result.startswith("Error: scheduled_at is in the past")
    rows = db.get_due_reminders()
    assert rows == []


def test_insert_allows_near_future(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    result = db.manage_state(
        "reminders",
        "insert",
        {"content": "学割証明書", "scheduled_at": future},
    )
    assert result.startswith("Inserted into reminders id=")
