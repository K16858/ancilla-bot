from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.memory.router import MemoryContext, retrieve_context


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def test_router_prefers_near_scope_and_loads_working(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "working_memory",
        "insert",
        {
            "scope_type": "task",
            "scope_id": "cap-refactor",
            "task_key": "cap-refactor",
            "goal": "add effect metadata",
            "state": "policy done",
            "status": "open",
        },
    )
    db.manage_state(
        "memories",
        "insert",
        {
            "kind": "fact",
            "subject": "task",
            "content": "alpha task note",
            "scope_type": "task",
            "scope_id": "cap-refactor",
        },
    )
    for i in range(3):
        db.manage_state(
            "memories",
            "insert",
            {
                "kind": "fact",
                "subject": f"user{i}",
                "content": f"alpha user note {i}",
                "scope_type": "user",
                "scope_id": "default",
            },
        )
    db.manage_state(
        "procedures",
        "insert",
        {
            "name": "add capability",
            "steps": "set effect then policy",
            "scope_type": "project",
            "scope_id": "ancilla",
        },
    )
    text = retrieve_context(
        "alpha effect",
        MemoryContext(user_id="default", project_id="ancilla", task_id="cap-refactor"),
    )
    assert text.startswith("## Relevant Memory")
    assert "goal: add effect metadata" in text
    semantic = text.split("### Semantic", 1)[1].split("###", 1)[0]
    assert "alpha task note" in semantic
    assert semantic.index("alpha task note") < semantic.index("alpha user note")
    assert semantic.count("alpha user note") == 2
    assert "set effect then policy" in text


def test_router_skips_denied_class_and_empty(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "memories",
        "insert",
        {
            "kind": "fact",
            "content": "alpha secret",
            "scope_type": "user",
            "scope_id": "default",
        },
    )

    def allowed(memory_class: str, *, write: bool = True) -> bool:
        return memory_class != "semantic"

    monkeypatch.setattr("ancilla_bot.memory.router.memory_class_allowed", allowed)
    assert retrieve_context("alpha", MemoryContext()) == ""
    assert retrieve_context("nothing-matches", MemoryContext()) == ""
