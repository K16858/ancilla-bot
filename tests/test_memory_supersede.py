from datetime import datetime, timedelta
from pathlib import Path

from ancilla_bot.heartbeat import db


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def test_same_memory_key_supersedes(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        {"kind": "profile", "subject": "language", "content": "en", "memory_key": "user.language"},
    )
    db.manage_state(
        "memories",
        "insert",
        {"kind": "profile", "subject": "language", "content": "ja", "memory_key": "user.language"},
    )
    rows = {r["id"]: r for r in db.list_memories()}
    old, new = min(rows), max(rows)
    assert rows[old]["lifecycle"] == "superseded"
    assert rows[new]["lifecycle"] == "active"
    assert rows[new]["content"] == "ja"
    assert rows[new]["supersedes"] == old


def test_short_goals_all_stay_active(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    for text in ("OSを作る", "論文を書く", "PCBを設計する"):
        db.manage_state("memories", "insert", {"kind": "goal", "subject": "short", "content": text})
    rows = db.list_memories()
    assert [r["lifecycle"] for r in rows] == ["active", "active", "active"]
    assert {r["content"] for r in rows} == {"OSを作る", "論文を書く", "PCBを設計する"}


def test_empty_subject_notes_all_stay_active(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    for text in ("A", "B", "C"):
        db.manage_state("memories", "insert", {"kind": "note", "subject": "", "content": text})
    rows = db.list_memories()
    assert len(rows) == 3
    assert all(r["lifecycle"] == "active" for r in rows)


def test_explicit_supersedes_one_row(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state("memories", "insert", {"kind": "note", "content": "old"})
    db.manage_state("memories", "insert", {"kind": "note", "content": "keep"})
    old_id = min(r["id"] for r in db.list_memories())
    db.manage_state(
        "memories",
        "insert",
        {"kind": "note", "content": "new", "supersedes": old_id},
    )
    rows = {r["id"]: r for r in db.list_memories()}
    assert rows[old_id]["lifecycle"] == "superseded"
    assert sum(1 for r in rows.values() if r["lifecycle"] == "active") == 2


def test_expired_memory_not_durable(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "subject": "tmp", "content": "gone", "expires_at": past},
    )
    assert db.list_memories(durable_only=True) == []
