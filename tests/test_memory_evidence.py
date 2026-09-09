from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.runtime.policy import gated_call


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def _step(*, status: str, action: str | None, observation: str) -> int:
    db.create_agent_run("run-1", source="user", user_input="hi")
    step_id = db.create_agent_run_step(
        "run-1",
        turn_index=0,
        status="running",
        action=action,
        action_input={"command": "echo"},
    )
    db.complete_agent_run_step(step_id, status, observation=observation, error=observation)
    return step_id


def test_denied_step_is_not_valid_evidence(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from ancilla_bot.core.run_context import run_source

    token = run_source.set("heartbeat")
    try:
        status, result = gated_call("bash", lambda **k: "ran", {"command": "echo hi"})
    finally:
        run_source.reset(token)
    assert status == "policy_denied"
    step_id = _step(status=status, action="bash", observation=result)
    out = db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "content": "from deny", "evidence_id": step_id},
    )
    assert out.startswith("Error: evidence_id")


def test_succeeded_step_is_valid_evidence(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    step_id = _step(status="tool_succeeded", action="web_search", observation="hits")
    out = db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "content": "from tool", "evidence_id": step_id},
    )
    assert out.startswith("Inserted")
    row = db.list_memories()[0]
    assert row["status"] == "observed"
    assert row["source_type"] == "tool"
    assert row["evidence_id"] == step_id
