import json
from datetime import datetime
from pathlib import Path

from ancilla_bot.heartbeat import db


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)


def test_agent_task_task_key_roundtrip(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    msg = db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-01 00:00:00",
            "content": "refactor capability",
            "task_key": "cap-refactor",
            "source": "heartbeat",
        },
    )
    assert msg.startswith("Inserted into agent_tasks")
    rows = json.loads(
        db.manage_state("agent_tasks", "select", {"task_key": "cap-refactor"})
    )
    assert rows[0]["task_key"] == "cap-refactor"
    assert rows[0]["status"] == "pending"
    found = db.get_agent_task_by_key("cap-refactor")
    assert found is not None
    assert found["content"] == "refactor capability"


def test_in_progress_agent_task_is_not_due(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-01 00:00:00",
            "content": "continue",
            "task_key": "cap-refactor",
            "status": "in_progress",
            "source": "heartbeat",
        },
    )
    db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-01 00:00:00",
            "content": "once",
            "source": "heartbeat",
        },
    )
    due = db.get_due_tasks(at=datetime(2099, 1, 2))
    agent = [row for row in due if row["_table"] == "agent_tasks"]
    assert [row["content"] for row in agent] == ["once"]
    assert agent[0]["task_key"] == ""


def test_open_working_memory_uses_task_scope(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "working_memory",
        "insert",
        {
            "scope_type": "task",
            "scope_id": "cap-refactor",
            "task_key": "cap-refactor",
            "goal": "add effect",
            "state": "policy done",
            "status": "open",
        },
    )
    db.manage_state(
        "working_memory",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "ancilla",
            "task_key": "cap-refactor",
            "goal": "other",
            "status": "open",
        },
    )
    row = db.get_open_working_memory("cap-refactor")
    assert row is not None
    assert row["scope_type"] == "task"
    assert row["goal"] == "add effect"
    assert db.get_open_working_memory("") is None
