from pathlib import Path

from ancilla_bot.core.run_context import run_source
from ancilla_bot.heartbeat import db


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def test_interactive_model_insert_is_hypothesis(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    token = run_source.set("user")
    try:
        db.manage_state(
            "memories",
            "insert",
            {"kind": "fact", "subject": "lang", "content": "loves Rust"},
        )
    finally:
        run_source.reset(token)
    row = db.list_memories()[0]
    assert row["status"] == "hypothesis"
    assert row["source_type"] == "model"
    assert db.list_memories(durable_only=True) == []


def test_payload_cannot_force_user_status(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        {
            "kind": "fact",
            "content": "spoof",
            "status": "user",
            "source_type": "user",
            "trusted_user": True,
        },
    )
    row = db.list_memories()[0]
    assert row["status"] == "hypothesis"


def test_trusted_user_insert_is_user(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "content": "from file"},
        trusted_user=True,
    )
    row = db.list_memories(durable_only=True)[0]
    assert row["status"] == "user"
    assert row["source_type"] == "user"


def test_interactive_update_does_not_promote_hypothesis(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state("memories", "insert", {"kind": "fact", "content": "guess"})
    row_id = db.list_memories()[0]["id"]
    token = run_source.set("user")
    try:
        db.manage_state("memories", "update", {"id": row_id, "content": "still guess"})
    finally:
        run_source.reset(token)
    row = db.list_memories()[0]
    assert row["status"] == "hypothesis"
    assert row["source_type"] == "model"
