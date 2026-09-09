from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.tools.registry import search_memory


def test_search_memory_ranks_user_facts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    monkeypatch.setenv("ANCILLA_RAG_ENABLED", "false")
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")
    db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "subject": "pet", "content": "likes cats", "importance": 0.9},
    )
    out = search_memory("cats")
    assert "likes cats" in out
    assert "[memory]" in out
