from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.tools.registry import search_memory


def test_search_memory_requires_scope_and_class(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")
    db.manage_state(
        "memories",
        "insert",
        {
            "kind": "fact",
            "subject": "pet",
            "content": "likes cats",
            "scope_type": "user",
            "scope_id": "default",
        },
    )
    assert search_memory("cats").startswith("Error: memory_class")
    out = search_memory(
        "cats",
        memory_class="semantic",
        scope_type="user",
        scope_id="default",
    )
    assert "likes cats" in out
    assert "[memory]" in out
    other = search_memory(
        "cats",
        memory_class="semantic",
        scope_type="project",
        scope_id="other",
    )
    assert other == "No matching memories found."


def test_search_memory_orders_by_match_count(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")
    db.manage_state(
        "memories",
        "insert",
        {
            "kind": "fact",
            "content": "cats",
            "scope_type": "user",
            "scope_id": "default",
        },
    )
    db.manage_state(
        "memories",
        "insert",
        {
            "kind": "fact",
            "subject": "pet",
            "predicate": "likes",
            "content": "cats and dogs",
            "scope_type": "user",
            "scope_id": "default",
        },
    )
    out = search_memory(
        "pet likes cats",
        memory_class="semantic",
        scope_type="user",
        scope_id="default",
        max_results=2,
    )
    first = out.split("\n\n")[0]
    assert "cats and dogs" in first
