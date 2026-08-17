"""MCP ツールを TOOL_REGISTRY に載せる。"""

from __future__ import annotations

from typing import Any, Callable

from loguru import logger

from ancilla_bot.mcp.manager import McpManager, get_manager

_MCP_TOOL_NAMES: set[str] = set()
_META_REGISTERED = False

MCP_NATIVE_SCHEMAS: dict[str, dict[str, Any]] = {}

_META_TOOLS = (
    "mcp_list_resources",
    "mcp_read_resource",
    "mcp_list_prompts",
    "mcp_get_prompt",
)


def namespaced_tool_name(server: str, tool_name: str) -> str:
    return f"{server}__{tool_name}"


def parse_namespaced_tool_name(full: str) -> tuple[str, str] | None:
    if "__" not in full:
        return None
    server, _, name = full.partition("__")
    if not server or not name:
        return None
    return server, name


def _empty_object_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False}


def _tool_schema(tool_input_schema: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(tool_input_schema, dict) and tool_input_schema.get("type") == "object":
        return tool_input_schema
    return _empty_object_schema()


def _make_mcp_tool(server: str, tool_name: str) -> Callable[..., str]:
    def _call(**kwargs: Any) -> str:
        return get_manager().call_tool(server, tool_name, dict(kwargs))

    _call.__name__ = namespaced_tool_name(server, tool_name)
    return _call


def mcp_list_resources(**kwargs: Any) -> str:
    _ = kwargs
    return get_manager().list_resources_text()


def mcp_read_resource(server: str, uri: str, **kwargs: Any) -> str:
    _ = kwargs
    return get_manager().read_resource(server, uri)


def mcp_list_prompts(**kwargs: Any) -> str:
    _ = kwargs
    return get_manager().list_prompts_text()


def mcp_get_prompt(
    server: str,
    name: str,
    arguments: dict[str, str] | None = None,
    **kwargs: Any,
) -> str:
    _ = kwargs
    return get_manager().get_prompt(server, name, arguments)


_META_DESCRIPTIONS: dict[str, str] = {
    "mcp_list_resources": (
        "List resources from connected MCP servers. action_input: {}."
    ),
    "mcp_read_resource": (
        "Read an MCP resource by server and URI. "
        'action_input: {"server": "name", "uri": "file:///..."}.'
    ),
    "mcp_list_prompts": (
        "List prompts from connected MCP servers. action_input: {}."
    ),
    "mcp_get_prompt": (
        "Get an MCP prompt by server and name. "
        'action_input: {"server": "name", "name": "prompt", "arguments": {}}.'
    ),
}

_META_SCHEMAS: dict[str, dict[str, Any]] = {
    "mcp_list_resources": _empty_object_schema(),
    "mcp_read_resource": {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name"},
            "uri": {"type": "string", "description": "Resource URI"},
        },
        "required": ["server", "uri"],
        "additionalProperties": False,
    },
    "mcp_list_prompts": _empty_object_schema(),
    "mcp_get_prompt": {
        "type": "object",
        "properties": {
            "server": {"type": "string", "description": "MCP server name"},
            "name": {"type": "string", "description": "Prompt name"},
            "arguments": {
                "type": "object",
                "description": "Prompt arguments",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["server", "name"],
        "additionalProperties": False,
    },
}


def register_meta_tools() -> None:
    from ancilla_bot.tools.registry import TOOL_DESCRIPTIONS, TOOL_REGISTRY

    _ensure_meta_tools(TOOL_REGISTRY, TOOL_DESCRIPTIONS)


def _ensure_meta_tools(
    registry: dict[str, Callable[..., str]],
    descriptions: dict[str, str],
) -> None:
    global _META_REGISTERED
    if _META_REGISTERED:
        return
    impls = {
        "mcp_list_resources": mcp_list_resources,
        "mcp_read_resource": mcp_read_resource,
        "mcp_list_prompts": mcp_list_prompts,
        "mcp_get_prompt": mcp_get_prompt,
    }
    for name in _META_TOOLS:
        if name in registry:
            logger.warning("mcp meta tool {} already exists; skipping", name)
            continue
        registry[name] = impls[name]
        descriptions[name] = _META_DESCRIPTIONS[name]
        MCP_NATIVE_SCHEMAS[name] = _META_SCHEMAS[name]
    _META_REGISTERED = True


def sync_registry_from_manager(manager: McpManager | None = None) -> None:
    from ancilla_bot.tools.registry import TOOL_DESCRIPTIONS, TOOL_REGISTRY

    mgr = manager or get_manager()
    register_meta_tools()

    desired: dict[str, tuple[str, str, dict[str, Any], str]] = {}
    for server, tool in mgr.get_tools():
        full = namespaced_tool_name(server, tool.name)
        if full in TOOL_REGISTRY and full not in _MCP_TOOL_NAMES:
            logger.warning("mcp tool {} collides with local tool; skipping", full)
            continue
        desc = tool.description or f"MCP tool {tool.name} from server {server}."
        desired[full] = (server, tool.name, _tool_schema(tool.input_schema), desc)

    for old in list(_MCP_TOOL_NAMES):
        if old not in desired:
            TOOL_REGISTRY.pop(old, None)
            TOOL_DESCRIPTIONS.pop(old, None)
            MCP_NATIVE_SCHEMAS.pop(old, None)
            _MCP_TOOL_NAMES.discard(old)

    for full, (server, tool_name, schema, desc) in desired.items():
        TOOL_REGISTRY[full] = _make_mcp_tool(server, tool_name)
        TOOL_DESCRIPTIONS[full] = desc
        MCP_NATIVE_SCHEMAS[full] = schema
        _MCP_TOOL_NAMES.add(full)
