from __future__ import annotations

from ancilla_bot.core.run_context import is_autonomous, run_source
from ancilla_bot.runtime.capability import get_capability

_AUTONOMOUS_DENY = frozenset({"external_write", "shell"})


def check(tool_name: str) -> str | None:
    cap = get_capability(tool_name)
    if cap is None:
        return None
    if is_autonomous() and cap.risk in _AUTONOMOUS_DENY:
        return (
            f"Error: capability '{tool_name}' ({cap.risk}) is denied for {run_source.get()}."
        )
    return None
