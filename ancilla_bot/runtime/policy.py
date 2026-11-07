from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ancilla_bot.core.run_context import is_autonomous, run_source
from ancilla_bot.runtime.capability import get_capability

ALLOW = "allow"
DENY = "deny"
REQUIRE_APPROVAL = "require_approval"

_AUTONOMOUS_DENY = frozenset({"external_write", "destructive", "privileged"})
_REQUIRE_APPROVAL = frozenset({"external_write", "destructive", "privileged"})


@dataclass(frozen=True)
class Decision:
    verdict: str
    message: str = ""


HOMELAB_ACTION_TOOL = "homelab_run_action"


def decide(tool_name: str, args: dict[str, Any] | None = None) -> Decision:
    """args は引数を見て判定するツール（homelab_run_action）用。args なしは fail closed で DENY。"""
    from ancilla_bot.runtime.persona import (
        tool_denied_by_persona,
        tool_requires_approval_by_persona,
    )

    cap = get_capability(tool_name)
    if cap is None:
        return Decision(DENY, f"Error: capability '{tool_name}' is not registered.")
    hook: Decision | None = None
    if tool_name == HOMELAB_ACTION_TOOL:
        # 主体 × Action × 対象 の細粒度判定（宣言は homelab.yaml）。effect は privileged のまま
        # = このフックを通らない経路は effect で承認必須/自律 DENY になる
        from ancilla_bot.homelab.actions import llm_verdict

        a = args if isinstance(args, dict) else {}
        verdict, msg = llm_verdict(
            a.get("action"), a.get("target"), {"lines": a.get("lines")}, is_autonomous()
        )
        hook = Decision(verdict, msg)
        if hook.verdict == DENY:
            return hook
    elif is_autonomous() and cap.effect in _AUTONOMOUS_DENY:
        return Decision(
            DENY,
            f"Error: capability '{tool_name}' ({cap.effect}) is denied for {run_source.get()}.",
        )
    if tool_requires_approval_by_persona(tool_name):
        return Decision(
            REQUIRE_APPROVAL,
            f"Error: capability '{tool_name}' requires approval for the active persona.",
        )
    if tool_denied_by_persona(tool_name):
        return Decision(
            DENY,
            f"Error: capability '{tool_name}' is denied for the active persona.",
        )
    if hook is not None:
        return hook
    if cap.effect in _REQUIRE_APPROVAL:
        return Decision(
            REQUIRE_APPROVAL,
            f"Error: capability '{tool_name}' ({cap.effect}) requires approval.",
        )
    return Decision(ALLOW)


def check(tool_name: str, args: dict[str, Any] | None = None) -> str | None:
    decision = decide(tool_name, args)
    if decision.verdict == ALLOW:
        return None
    return decision.message


def gated_call(
    tool_name: str,
    func: Callable[..., str],
    args: dict[str, Any],
) -> tuple[str, str]:
    decision = decide(tool_name, args)
    if decision.verdict == DENY:
        return "policy_denied", decision.message
    if decision.verdict == REQUIRE_APPROVAL:
        return "approval_pending", decision.message
    return "tool_succeeded", func(**args)
