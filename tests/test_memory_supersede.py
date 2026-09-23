from datetime import datetime, timedelta
from pathlib import Path

from ancilla_bot.heartbeat import db


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def _scope(**extra):
    return {"scope_type": "user", "scope_id": "default", **extra}


def test_same_memory_key_supersedes(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        _scope(kind="profile", subject="language", content="en", memory_key="user.language"),
    )
    db.manage_state(
        "memories",
        "insert",
        _scope(kind="profile", subject="language", content="ja", memory_key="user.language"),
    )
    active = db.list_memories(durable_only=False)
    # durable_only=False still drops expired; superseded rows get expires_at closed.
    assert len([r for r in active if r["lifecycle"] == "active"]) == 1
    assert active[0]["content"] == "ja"
    import json

    raw = db.manage_state(
        "memories",
        "select",
        {"lifecycle": "superseded", "scope_type": "user", "scope_id": "default", "limit": 10},
    )
    closed = json.loads(raw)
    assert len(closed) == 1
    assert closed[0]["content"] == "en"
    assert closed[0]["expires_at"]
    assert active[0]["supersedes"] == closed[0]["id"]


def test_memory_key_does_not_cross_scope(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        _scope(kind="fact", content="a", memory_key="host.ram"),
    )
    db.manage_state(
        "memories",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "ancilla",
            "kind": "fact",
            "content": "b",
            "memory_key": "host.ram",
        },
    )
    rows = db.list_memories()
    assert len(rows) == 2
    assert all(r["lifecycle"] == "active" for r in rows)


def test_supersedes_rejects_other_scope(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state("memories", "insert", _scope(kind="note", content="old"))
    old_id = db.list_memories()[0]["id"]
    out = db.manage_state(
        "memories",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "ancilla",
            "kind": "note",
            "content": "new",
            "supersedes": old_id,
        },
    )
    assert out.startswith("Error: supersedes must refer")


def test_lifecycle_update_allows_archived_only(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state("memories", "insert", _scope(kind="note", content="x"))
    row_id = db.list_memories()[0]["id"]
    assert db.manage_state("memories", "update", {"id": row_id, "lifecycle": "archived"}).startswith(
        "Updated"
    )
    assert db.manage_state("memories", "update", {"id": row_id, "lifecycle": "superseded"}).startswith(
        "Error: lifecycle"
    )


def test_short_goals_all_stay_active(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    for text in ("OSを作る", "論文を書く", "PCBを設計する"):
        db.manage_state("memories", "insert", _scope(kind="goal", subject="short", content=text))
    rows = db.list_memories()
    assert [r["lifecycle"] for r in rows] == ["active", "active", "active"]
    assert {r["content"] for r in rows} == {"OSを作る", "論文を書く", "PCBを設計する"}


def test_empty_subject_notes_all_stay_active(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    for text in ("A", "B", "C"):
        db.manage_state("memories", "insert", _scope(kind="note", subject="", content=text))
    rows = db.list_memories()
    assert len(rows) == 3
    assert all(r["lifecycle"] == "active" for r in rows)


def test_explicit_supersedes_one_row(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state("memories", "insert", _scope(kind="note", content="old"))
    db.manage_state("memories", "insert", _scope(kind="note", content="keep"))
    old_id = min(r["id"] for r in db.list_memories())
    db.manage_state(
        "memories",
        "insert",
        _scope(kind="note", content="new", supersedes=old_id),
    )
    import json

    active = [r for r in db.list_memories() if r["lifecycle"] == "active"]
    assert {r["content"] for r in active} == {"keep", "new"}
    closed = json.loads(
        db.manage_state(
            "memories",
            "select",
            {"lifecycle": "superseded", "scope_type": "user", "scope_id": "default", "limit": 10},
        )
    )
    assert len(closed) == 1
    assert closed[0]["id"] == old_id
    assert closed[0]["content"] == "old"


def test_expired_memory_not_durable(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.manage_state(
        "memories",
        "insert",
        _scope(kind="fact", subject="tmp", content="gone", expires_at=past),
    )
    assert db.list_memories(durable_only=True) == []


def test_insert_requires_scope(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    out = db.manage_state("memories", "insert", {"kind": "fact", "content": "no scope"})
    assert out.startswith("Error: scope_type and scope_id")


def test_scope_id_is_stored_whole(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    scope_id = "s" * 240
    db.manage_state(
        "memories",
        "insert",
        {"scope_type": "project", "scope_id": scope_id, "kind": "fact", "content": "long"},
    )
    assert db.list_memories()[0]["scope_id"] == scope_id


def test_predicate_and_valid_from_stored(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        _scope(
            kind="fact",
            subject="Akari",
            predicate="role",
            content="Docker host",
            valid_from="2026-01-01 00:00:00",
        ),
    )
    row = db.list_memories()[0]
    assert row["predicate"] == "role"
    assert row["scope_type"] == "user"
    assert row["scope_id"] == "default"
    assert row["valid_from"] == "2026-01-01 00:00:00"
