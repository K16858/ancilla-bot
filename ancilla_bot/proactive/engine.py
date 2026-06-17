"""
Proactive Engine
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ProactiveAction:
    type: str
    content: str
    priority: int
    trigger: str


def _eval_condition(condition: str, ctx: dict[str, Any]) -> bool:
    gap = int(ctx.get("conversation_gap_seconds") or 0)
    is_active = bool(ctx.get("is_active_hours"))
    new_files = ctx.get("filesystem_new_files")
    goal_days = ctx.get("goal_deadline_within_days")
    camera = bool(ctx.get("camera_person_detected"))

    if condition == "conversation_gap_seconds > 14400 AND is_active_hours":
        return gap > 14400 and is_active
    if condition == "filesystem_new_files IS NOT NULL":
        return bool(new_files)
    if condition == "goal_deadline_within_days <= 3":
        return goal_days is not None and int(goal_days) <= 3
    if condition == "camera_person_detected AND conversation_gap_seconds > 3600":
        return camera and gap > 3600
    return False


def _build_context(snapshot: dict[str, Any], personal_model: dict[str, Any]) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    time_sig = snapshot.get("time", {}).get("value", {})
    gap_sig = snapshot.get("conversation_gap", {}).get("value", {})
    fs_sig = snapshot.get("filesystem", {}).get("value", {})
    cam_sig = snapshot.get("camera", {}).get("value", {})

    ctx["is_active_hours"] = time_sig.get("is_active_hours", False)
    ctx["conversation_gap_seconds"] = gap_sig.get("conversation_gap_seconds", 0)
    ctx["filesystem_new_files"] = fs_sig.get("filesystem_new_files")
    ctx["camera_person_detected"] = cam_sig.get("camera_person_detected", False)

    short_goals = personal_model.get("goals", {}).get("short_term") or []
    for goal in short_goals:
        if isinstance(goal, dict) and goal.get("deadline_within_days") is not None:
            ctx["goal_deadline_within_days"] = goal.get("deadline_within_days")
            ctx["goal"] = goal.get("goal", "")
            break
    return ctx


def evaluate(
    context_snapshot: dict[str, Any],
    personal_model: dict[str, Any],
    rules: list[dict[str, Any]],
    last_interaction_dt: datetime,
) -> ProactiveAction | None:
    """シグナル + 個人モデル + ルールから介入を決定する。"""
    _ = last_interaction_dt
    ctx = _build_context(context_snapshot, personal_model)
    tolerance = (
        personal_model.get("patterns", {}).get("interruption_tolerance") or "low"
    )
    for rule in rules:
        if not _eval_condition(str(rule.get("condition", "")), ctx):
            continue
        template = str(rule.get("message_template", ""))
        content = template.format(goal=ctx.get("goal", ""))
        priority = 2 if tolerance == "medium" else (3 if tolerance == "high" else 1)
        return ProactiveAction(
            type=str(rule.get("action", "notify")),
            content=content,
            priority=priority,
            trigger=str(rule.get("id", "unknown")),
        )
    return None
