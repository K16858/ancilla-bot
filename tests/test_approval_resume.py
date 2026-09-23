from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.runtime import approval as approval_mod
from ancilla_bot.runtime.approval import (
    approve_run,
    reject_run,
    save_pending_approval,
    try_handle_approval_command,
)
from ancilla_bot.tools import registry as registry_mod


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    db.ensure_schema()


def test_try_handle_approval_command_parses():
    assert try_handle_approval_command("hello") is None
    assert "not found" in (try_handle_approval_command("approve missing-id") or "")


def test_reject_pending_approval(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.create_agent_run("run-1", source="user", user_input="x")
    msg = save_pending_approval(
        run_id="run-1",
        tool_name="demo__write",
        args={"path": "/tmp"},
        turn_index=0,
        step_id=db.create_agent_run_step(
            "run-1", turn_index=0, status="llm_responded", action="demo__write", action_input={}
        ),
        messages=[{"role": "user", "content": "x"}],
        source="user",
    )
    assert "approve run-1" in msg
    assert db.get_agent_run("run-1")["status"] == "awaiting_approval"
    out = reject_run("run-1")
    assert "Rejected" in out
    assert db.get_agent_run("run-1")["status"] == "cancelled"
    pending = db.get_pending_approval("run-1")
    assert pending is None


def test_approve_runs_tool_and_continues(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    called = {"n": 0}

    def demo_tool(**kwargs):
        called["n"] += 1
        return "wrote"

    registry_mod.TOOL_REGISTRY["demo__write"] = demo_tool

    class FakeCaller:
        def call(self, messages, images=None):
            from ancilla_bot.llm.tool_adapter import ToolCallResult

            return ToolCallResult(
                action=None,
                action_input=None,
                thought="",
                final_answer="done after approve",
                emotion=None,
                raw="done after approve",
                assistant_message=None,
            )

    monkeypatch.setattr(
        "ancilla_bot.core.agent_loop.get_tool_caller",
        lambda: FakeCaller(),
    )
    monkeypatch.setattr(
        "ancilla_bot.core.agent_loop.build_tools_system_prompt",
        lambda: "sys",
    )
    monkeypatch.setattr("ancilla_bot.core.agent_loop.VERIFY_ANSWER", False)

    try:
        db.create_agent_run("run-2", source="user", user_input="write")
        step_id = db.create_agent_run_step(
            "run-2",
            turn_index=0,
            status="approval_pending",
            action="demo__write",
            action_input={"x": 1},
        )
        save_pending_approval(
            run_id="run-2",
            tool_name="demo__write",
            args={"x": 1},
            turn_index=0,
            step_id=step_id,
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "write"},
            ],
            assistant_raw='{"action":"demo__write"}',
            source="user",
        )
        out = approve_run("run-2")
        assert called["n"] == 1
        assert "done after approve" in out
        assert db.get_agent_run("run-2")["status"] == "completed"
        assert db.get_pending_approval("run-2") is None
    finally:
        registry_mod.TOOL_REGISTRY.pop("demo__write", None)
