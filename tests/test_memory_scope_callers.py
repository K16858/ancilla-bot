from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.memory.store import maybe_import_user_md, project_memories
from ancilla_bot.personal_model import update_user_goal


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")
    return ws


def test_update_user_goal_inserts_with_user_scope(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    out = update_user_goal("ship Ancilla", term="short")
    assert not out.startswith("Error:")
    row = db.list_memories()[0]
    assert row["kind"] == "goal"
    assert row["subject"] == "short"
    assert row["content"] == "ship Ancilla"
    assert row["scope_type"] == "user"
    assert row["scope_id"] == "default"


def test_maybe_import_user_md_inserts_with_user_scope(tmp_path: Path, monkeypatch):
    ws = _db(tmp_path, monkeypatch)
    (ws / "USER.md").write_text(
        "# ユーザーについて\n\n## プロフィール\n- name: Alice\n",
        encoding="utf-8",
    )
    maybe_import_user_md()
    rows = db.list_memories(durable_only=True)
    assert len(rows) == 1
    assert rows[0]["kind"] == "profile"
    assert rows[0]["scope_type"] == "user"
    assert rows[0]["scope_id"] == "default"
    assert "Alice" in rows[0]["content"]
    project_memories()
    assert "Alice" in (ws / "USER.md").read_text(encoding="utf-8")
    assert "Alice" in (tmp_path / "model.yaml").read_text(encoding="utf-8")
