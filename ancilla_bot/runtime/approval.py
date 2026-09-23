"""Human-in-the-loop approval for gated tool calls."""

from __future__ import annotations

import re
from typing import Any

from ancilla_bot.heartbeat.db import (
    create_pending_approval,
    get_agent_run,
    get_pending_approval,
    resolve_pending_approval,
    update_agent_run_status,
)

_APPROVE_RE = re.compile(r"^\s*(?:/)?approve\s+(\S+)\s*$", re.IGNORECASE)
_REJECT_RE = re.compile(r"^\s*(?:/)?reject\s+(\S+)\s*$", re.IGNORECASE)


def approval_request_message(run_id: str, tool_name: str, args: dict[str, Any]) -> str:
    return (
        f"承認が必要です (run_id={run_id})\n"
        f"tool: {tool_name}\n"
        f"args: {args}\n"
        f"承認: approve {run_id}\n"
        f"拒否: reject {run_id}"
    )


def save_pending_approval(
    *,
    run_id: str,
    tool_name: str,
    args: dict[str, Any],
    turn_index: int,
    step_id: int,
    messages: list[dict[str, Any]],
    assistant_raw: str = "",
    assistant_message: dict[str, Any] | None = None,
    source: str = "",
) -> str:
    from ancilla_bot.skills.evolution import snapshot_loaded_skills

    create_pending_approval(
        run_id=run_id,
        tool_name=tool_name,
        args=args,
        turn_index=turn_index,
        step_id=step_id,
        messages=messages,
        assistant_raw=assistant_raw,
        assistant_message=assistant_message,
        source=source,
        skill_loads=list(snapshot_loaded_skills()),
    )
    update_agent_run_status(run_id, "awaiting_approval")
    return approval_request_message(run_id, tool_name, args)


def try_handle_approval_command(text: str) -> str | None:
    raw = (text or "").strip()
    m = _APPROVE_RE.match(raw)
    if m:
        return approve_run(m.group(1))
    m = _REJECT_RE.match(raw)
    if m:
        return reject_run(m.group(1))
    return None


def reject_run(run_id: str) -> str:
    run = get_agent_run(run_id)
    if run is None:
        return f"agent_run not found: {run_id}"
    pending = get_pending_approval(run_id)
    if pending is None:
        return f"No pending approval for run: {run_id}"
    resolve_pending_approval(int(pending["id"]), "rejected")
    update_agent_run_status(run_id, "cancelled", last_error="approval rejected")
    return f"Rejected tool {pending['tool_name']} for run {run_id}."


def approve_run(run_id: str) -> str:
    from ancilla_bot.core.agent_loop import continue_after_approval

    run = get_agent_run(run_id)
    if run is None:
        return f"agent_run not found: {run_id}"
    if run.get("status") != "awaiting_approval":
        return f"Run {run_id} is not awaiting approval (status={run.get('status')})."
    pending = get_pending_approval(run_id)
    if pending is None:
        return f"No pending approval for run: {run_id}"
    answer, _emotion = continue_after_approval(run_id, pending)
    return answer
