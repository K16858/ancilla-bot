from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ancilla_bot.core.run_context import is_autonomous, run_source
from ancilla_bot.runtime.capability import get_capability

ALLOW = "allow"
DENY = "deny"
REQUIRE_APPROVAL = "require_approval"

_AUTONOMOUS_DENY = frozenset({"external_write", "shell"})
_REQUIRE_APPROVAL = frozenset()


@dataclass(frozen=True)
class Decision:
    verdict: str
    message: str = ""


def decide(tool_name: str) -> Decision:
    cap = get_capability(tool_name)
    if cap is None:
        return Decision(ALLOW)
    if is_autonomous() and cap.risk in _AUTONOMOUS_DENY:
        return Decision(
            DENY,
            f"Error: capability '{tool_name}' ({cap.risk}) is denied for {run_source.get()}.",
        )
    if cap.risk in _REQUIRE_APPROVAL:
        return Decision(
            REQUIRE_APPROVAL,
            f"Error: capability '{tool_name}' ({cap.risk}) requires approval.",
        )
    return Decision(ALLOW)


def check(tool_name: str) -> str | None:
    decision = decide(tool_name)
    if decision.verdict == ALLOW:
        return None
    return decision.message


def gated_call(
    tool_name: str,
    func: Callable[..., str],
    args: dict[str, Any],
) -> tuple[str, str]:
    decision = decide(tool_name)
    if decision.verdict == DENY:
        return "policy_denied", decision.message
    if decision.verdict == REQUIRE_APPROVAL:
        return "approval_pending", decision.message
    return "tool_succeeded", func(**args)
