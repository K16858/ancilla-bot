from datetime import datetime, timedelta
from pathlib import Path

from ancilla_bot.heartbeat import db


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def test_insert_supersedes_same_kind_subject(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state("memories", "insert", {"kind": "fact", "subject": "pet", "content": "cat"})
    db.manage_state("memories", "insert", {"kind": "fact", "subject": "pet", "content": "dog"})
    rows = db.list_memories()
    by_id = {r["id"]: r for r in rows}
    old = min(by_id)
    new = max(by_id)
    assert by_id[old]["lifecycle"] == "superseded"
    assert by_id[new]["lifecycle"] == "active"
    assert by_id[new]["supersedes"] == old
    durable = db.list_memories(durable_only=True)
    assert [r["content"] for r in durable] == ["dog"]


def test_expired_memory_not_durable(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "subject": "tmp", "content": "gone", "expires_at": past},
    )
    assert db.list_memories(durable_only=True) == []
