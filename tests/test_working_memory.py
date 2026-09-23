import json
from pathlib import Path

from ancilla_bot.heartbeat import db


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()


def test_working_memory_insert_and_select(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    out = db.manage_state(
        "working_memory",
        "insert",
        {
            "scope_type": "task",
            "scope_id": "deploy-whisper",
            "task_key": "whisper",
            "goal": "STT available",
            "state": "compose ready",
            "next_actions": "docker compose up",
            "resources": "host=Akari",
        },
    )
    assert out.startswith("Inserted")
    raw = db.manage_state(
        "working_memory",
        "select",
        {
            "scope_type": "task",
            "scope_id": "deploy-whisper",
            "task_key": "whisper",
            "limit": 5,
        },
    )
    rows = json.loads(raw)
    assert len(rows) == 1
    assert rows[0]["goal"] == "STT available"
    assert rows[0]["status"] == "open"


def test_working_memory_rejects_duplicate_open(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    payload = {
        "scope_type": "task",
        "scope_id": "deploy-whisper",
        "task_key": "whisper",
        "goal": "first",
    }
    assert db.manage_state("working_memory", "insert", payload).startswith("Inserted")
    err = db.manage_state("working_memory", "insert", payload)
    assert err.startswith("Error: open working_memory already exists")
    row_id = json.loads(
        db.manage_state(
            "working_memory",
            "select",
            {"scope_type": "task", "scope_id": "deploy-whisper", "task_key": "whisper"},
        )
    )[0]["id"]
    assert db.manage_state(
        "working_memory",
        "update",
        {"id": row_id, "state": "running", "status": "open"},
    ).startswith("Updated")


def test_working_memory_update_rejects_second_open(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "working_memory",
        "insert",
        {"scope_type": "task", "scope_id": "t", "task_key": "a", "goal": "a"},
    )
    db.manage_state(
        "working_memory",
        "insert",
        {"scope_type": "task", "scope_id": "t", "task_key": "b", "goal": "b", "status": "done"},
    )
    rows = json.loads(
        db.manage_state(
            "working_memory",
            "select",
            {"scope_type": "task", "scope_id": "t", "limit": 10},
        )
    )
    done_id = next(r["id"] for r in rows if r["task_key"] == "b")
    err = db.manage_state(
        "working_memory",
        "update",
        {"id": done_id, "task_key": "a", "status": "open"},
    )
    assert err.startswith("Error: open working_memory already exists")
