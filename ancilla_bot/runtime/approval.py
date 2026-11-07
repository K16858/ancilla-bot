"""Human-in-the-loop approval for gated tool calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

from ancilla_bot.heartbeat.db import (
    create_pending_approval,
    get_agent_run,
    claim_pending_approval,
    get_pending_approval,
    list_pending_approvals,
    pending_approvals_signature,
    resolve_pending_approval,
    update_agent_run_status,
)

_APPROVE_RE = re.compile(r"^\s*(?:/)?approve\s+(\S+)\s*$", re.IGNORECASE)
_REJECT_RE = re.compile(r"^\s*(?:/)?reject\s+(\S+)\s*$", re.IGNORECASE)


def _homelab_detail(args: dict[str, Any], created: datetime | None = None) -> str:
    """homelab_run_action の承認文: 操作・対象・引数・期限を明示する。"""
    from ancilla_bot.homelab import actions, operations

    ttl = float(os.getenv("ANCILLA_APPROVAL_TTL_HOURS", "24") or 24)
    until = ((created or datetime.now()) + timedelta(hours=ttl)).strftime("%Y-%m-%d %H:%M")
    try:
        r = actions.resolve(args.get("action"), args.get("target"), {"lines": args.get("lines")})
        where, extra = f"{r.target} ({r.kind}: {r.unit} @ {r.host_id})", r.args
    except actions.ActionError as e:
        where, extra = f"{args.get('target')} (宣言を確認できません: {e})", {}
    return (
        f"操作: {args.get('action')}\n対象: {where}\n引数: {extra or '(なし)'}\n"
        f"承認の期限: {until} まで（承認後に Node へ送る命令は {operations.COMMAND_TTL_SEC} 秒で失効）\n"
    )


def approval_request_message(run_id: str, tool_name: str, args: dict[str, Any]) -> str:
    detail = _homelab_detail(args) if tool_name == "homelab_run_action" else ""
    return (
        f"承認が必要です (run_id={run_id})\n"
        f"tool: {tool_name}\n"
        f"{detail}"
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


def try_handle_approval_command(text: str, by: str = "chat") -> str | None:
    raw = (text or "").strip()
    m = _APPROVE_RE.match(raw)
    if m:
        return approve_run(m.group(1), by)
    m = _REJECT_RE.match(raw)
    if m:
        return reject_run(m.group(1), by)
    return None


def list_pending() -> list[dict[str, Any]]:
    """Client API 用: 承認待ちの一覧（説明文と期限つき）。"""
    ttl = float(os.getenv("ANCILLA_APPROVAL_TTL_HOURS", "24") or 24)
    out = []
    for p in list_pending_approvals():
        args = json.loads(p.pop("args_json") or "{}")
        created = datetime.strptime(str(p["created_at"]), "%Y-%m-%d %H:%M:%S")
        detail = _homelab_detail(args, created) if p["tool_name"] == "homelab_run_action" else ""
        out.append({
            "run_id": p["run_id"], "tool": p["tool_name"], "args": args, "description": detail,
            "created_at": p["created_at"], "expires_at": (created + timedelta(hours=ttl)).strftime("%Y-%m-%d %H:%M:%S"),
            "source": p["source"],
        })
    return out


def signature() -> str:
    return hashlib.sha256(repr(pending_approvals_signature()).encode()).hexdigest()


def _expired(pending: dict[str, Any]) -> bool:
    ttl = float(os.getenv("ANCILLA_APPROVAL_TTL_HOURS", "24") or 24)
    created = datetime.strptime(str(pending["created_at"]), "%Y-%m-%d %H:%M:%S")
    return datetime.now() - created > timedelta(hours=ttl)


def reject_run(run_id: str, by: str = "cli") -> str:
    run = get_agent_run(run_id)
    if run is None:
        return f"agent_run not found: {run_id}"
    pending = get_pending_approval(run_id)
    if pending is None:
        return f"No pending approval for run: {run_id}"
    if not claim_pending_approval(int(pending["id"]), by):
        return f"No pending approval for run: {run_id}"
    resolve_pending_approval(int(pending["id"]), "rejected")
    update_agent_run_status(run_id, "cancelled", last_error="approval rejected")
    return f"Rejected tool {pending['tool_name']} for run {run_id}."


def approve_run(run_id: str, by: str = "cli") -> str:
    from ancilla_bot.core.agent_loop import continue_after_approval
    from ancilla_bot.core.run_context import approver

    run = get_agent_run(run_id)
    if run is None:
        return f"agent_run not found: {run_id}"
    if run.get("status") != "awaiting_approval":
        return f"Run {run_id} is not awaiting approval (status={run.get('status')})."
    pending = get_pending_approval(run_id)
    if pending is None:
        return f"No pending approval for run: {run_id}"
    if _expired(pending):
        resolve_pending_approval(int(pending["id"]), "rejected")
        update_agent_run_status(run_id, "cancelled", last_error="approval expired")
        return f"Approval for run {run_id} expired; rejected."
    if not claim_pending_approval(int(pending["id"]), by):  # 同時承認の負け側は実行しない
        return f"Approval for run {run_id} was already handled."
    token = approver.set(by)
    try:
        answer, _emotion = continue_after_approval(run_id, pending)
    except BaseException:
        resolve_pending_approval(int(pending["id"]), "failed")
        raise
    finally:
        approver.reset(token)
    return answer
