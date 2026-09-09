from __future__ import annotations

import os

from ancilla_bot.core.run_context import run_source
from ancilla_bot.runtime.mode import get_active_mode


def format_runtime_self_model() -> str:
    from ancilla_bot.runtime.capability import list_capabilities

    caps = list_capabilities()
    names = [c.name for c in caps if "__" not in c.name]
    mcp_n = sum(1 for c in caps if "__" in c.name)
    sandbox = os.getenv("ANCILLA_SANDBOX", "none").strip() or "none"
    allow = os.getenv("ANCILLA_BASH_ALLOWLIST", "").strip() or "(none)"
    lines = [
        "## Runtime self model",
        f"active_mode: {get_active_mode().name}",
        f"run_source: {run_source.get()}",
        f"sandbox: {sandbox}",
        f"bash_allowlist: {allow}",
        "permissions:",
        "  shell: deny_autonomous",
        "  external_write: deny_autonomous",
        "capabilities: " + ", ".join(names),
    ]
    if mcp_n:
        lines.append(f"mcp_tools: {mcp_n}")
    return "\n".join(lines)
