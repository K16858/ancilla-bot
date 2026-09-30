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


def test_open_working_memory_keeps_task_off_due(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-01 00:00:00",
            "content": "refactor capability",
            "task_key": "cap-refactor",
            "source": "heartbeat",
        },
    )
    task = db.get_agent_task_by_key("cap-refactor")
    assert task is not None
    created = db.ensure_open_working_memory("cap-refactor", goal="refactor capability")
    assert created.startswith("Inserted")
    assert db.ensure_open_working_memory("cap-refactor", goal="again") == ""
    assert db.settle_agent_task_after_run(int(task["id"]), "cap-refactor") == "in_progress"
    due = db.get_due_tasks(at=datetime(2099, 1, 2))
    assert [row["content"] for row in due if row["_table"] == "agent_tasks"] == []
    wm = db.get_open_working_memory("cap-refactor")
    assert wm is not None
    updated = db.manage_state(
        "working_memory",
        "update",
        {"id": wm["id"], "status": "done"},
    )
    assert updated.startswith("Updated")
    assert db.settle_agent_task_after_run(int(task["id"]), "cap-refactor") == "completed"
    done = db.get_agent_task_by_key("cap-refactor")
    assert done is not None
    assert done["status"] == "completed"
    assert done["completed"] == 1


def test_wakeup_restores_persona_and_working_memory(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    _db(tmp_path, monkeypatch)
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-01 00:00:00",
            "content": "research the paper",
            "task_key": "paper",
            "persona": "researcher",
            "source": "heartbeat",
            "status": "in_progress",
        },
    )
    db.ensure_open_working_memory("paper", goal="read the abstract")
    db.manage_state(
        "reminders",
        "insert",
        {
            "scheduled_at": "2099-01-01 10:00:00",
            "content": "resume paper",
            "kind": "agent_wakeup",
            "task_key": "paper",
        },
    )
    wakeups = db.get_due_reminders(at=datetime(2099, 1, 2), kind="agent_wakeup")
    assert len(wakeups) == 1
    assert wakeups[0]["task_key"] == "paper"
    from ancilla_bot.memory.router import MemoryContext, retrieve_context

    persona, task_key = db.wakeup_resume(wakeups)
    assert persona == "researcher"
    assert task_key == "paper"
    text = retrieve_context("resume", MemoryContext(task_id=task_key))
    assert "read the abstract" in text

