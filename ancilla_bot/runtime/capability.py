from __future__ import annotations

from dataclasses import dataclass

from ancilla_bot.tools.registry import TOOL_DESCRIPTIONS, TOOL_REGISTRY, _short_tool_description

# tool name -> (effect, scope)
_BUILTIN: dict[str, tuple[str, str]] = {
    "bash": ("privileged", "os"),
    "write_file": ("local_write", "workspace"),
    "edit_file_safe": ("local_write", "workspace"),
    "trash_file": ("destructive", "workspace"),
    "move_file": ("local_write", "workspace"),
    "read_file": ("local_read", "workspace"),
    "list_workspace": ("local_read", "workspace"),
    "workspace_inventory": ("local_read", "workspace"),
    "manage_state": ("local_write", "memory"),
    "update_user_goal": ("local_write", "memory"),
    "search_memory": ("local_read", "memory"),
    "get_user_context": ("local_read", "memory"),
    "load_skill": ("local_read", "memory"),
    "set_persona": ("local_read", "memory"),
    "finish": ("local_read", "memory"),
    "notify_user": ("local_write", "os"),
    "get_time": ("local_read", "os"),
    "web_search": ("external_read", "web"),
    "fetch_page": ("external_read", "web"),
    "search_arxiv": ("external_read", "web"),
    "end_edge_session": ("local_read", "os"),
    "use_edgedevice": ("local_read", "os"),
    "get_image": ("local_read", "os"),
    "get_audio": ("local_read", "os"),
    "mcp_list_resources": ("external_read", "mcp"),
    "mcp_read_resource": ("external_read", "mcp"),
    "mcp_list_prompts": ("external_read", "mcp"),
    "mcp_get_prompt": ("external_read", "mcp"),
}

# MCP tools registered via bridge; cleared/updated on sync. name -> (effect, scope)
_MCP: dict[str, tuple[str, str]] = {}


@dataclass(frozen=True)
class Capability:
    name: str
    tool_name: str
    effect: str
    scope: str
    available: bool = True


def set_mcp_effect(tool_name: str, effect: str, scope: str) -> None:
    _MCP[tool_name] = (effect, scope)


def clear_mcp_effects() -> None:
    _MCP.clear()


def _spec(tool_name: str) -> tuple[str, str]:
    if tool_name in _BUILTIN:
        return _BUILTIN[tool_name]
    if tool_name in _MCP:
        return _MCP[tool_name]
    if "__" in tool_name:
        server = tool_name.split("__", 1)[0]
        return ("external_write", server)
    return ("local_read", "workspace")


def effect_for(tool_name: str) -> str:
    return _spec(tool_name)[0]


def scope_for(tool_name: str) -> str:
    return _spec(tool_name)[1]


def list_capabilities() -> list[Capability]:
    return [
        Capability(
            name=name,
            tool_name=name,
            effect=effect_for(name),
            scope=scope_for(name),
            available=True,
        )
        for name in TOOL_REGISTRY
    ]


def get_capability(name: str) -> Capability | None:
    if name not in TOOL_REGISTRY:
        return None
    return Capability(
        name=name,
        tool_name=name,
        effect=effect_for(name),
        scope=scope_for(name),
        available=True,
    )


def format_tools_block(*, native: bool) -> str:
    lines = []
    for name in TOOL_REGISTRY:
        desc = TOOL_DESCRIPTIONS.get(name, name)
        if native:
            lines.append(f"- {name}: {_short_tool_description(desc)}")
        else:
            lines.append(f"- {name}: {desc}")
    return "\n".join(lines)
