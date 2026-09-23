from __future__ import annotations

from dataclasses import dataclass

from ancilla_bot.tools.registry import TOOL_DESCRIPTIONS, TOOL_REGISTRY, _short_tool_description

_RISK = {
    "bash": "shell",
    "write_file": "workspace_write",
    "edit_file_safe": "workspace_write",
    "trash_file": "workspace_write",
    "move_file": "workspace_write",
    "manage_state": "state",
    "update_user_goal": "state",
    "notify_user": "notify",
    "mcp_list_resources": "external_read",
    "mcp_read_resource": "external_read",
    "mcp_list_prompts": "external_read",
    "mcp_get_prompt": "external_read",
}

# MCP tools registered via bridge; cleared/updated on sync.
_MCP_RISKS: dict[str, str] = {}


@dataclass(frozen=True)
class Capability:
    name: str
    tool_name: str
    risk: str
    available: bool = True


def set_mcp_risk(tool_name: str, risk: str) -> None:
    _MCP_RISKS[tool_name] = risk


def clear_mcp_risks() -> None:
    _MCP_RISKS.clear()


def risk_for(tool_name: str) -> str:
    if tool_name in _RISK:
        return _RISK[tool_name]
    if tool_name in _MCP_RISKS:
        return _MCP_RISKS[tool_name]
    if "__" in tool_name:
        return "external_write"
    return "read_only"


def list_capabilities() -> list[Capability]:
    return [
        Capability(name=name, tool_name=name, risk=risk_for(name), available=True)
        for name in TOOL_REGISTRY
    ]


def get_capability(name: str) -> Capability | None:
    if name not in TOOL_REGISTRY:
        return None
    return Capability(name=name, tool_name=name, risk=risk_for(name), available=True)


def format_tools_block(*, native: bool) -> str:
    lines = []
    for name in TOOL_REGISTRY:
        desc = TOOL_DESCRIPTIONS.get(name, name)
        if native:
            lines.append(f"- {name}: {_short_tool_description(desc)}")
        else:
            lines.append(f"- {name}: {desc}")
    return "\n".join(lines)
