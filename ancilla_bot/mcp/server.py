"""
Ancilla を MCP Server として公開する。外部には ask_ancilla のみ。
"""

from __future__ import annotations

import threading

from loguru import logger
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS

from ancilla_bot.core.agent_loop import run_agent_loop_with_tools
from ancilla_bot.core.execution import get_runtime
from ancilla_bot.llm.context_window import resolve_max_history_chars
from ancilla_bot.memory.short_term import append_and_trim

INSTRUCTIONS = "Talk to Ancilla. Pass the user's message in the message argument."
_MAX_HISTORY_CHARS = resolve_max_history_chars()
_DEFAULT_SESSION = "default"
_NON_TOOL_METHODS = (
    "prompts/list",
    "prompts/get",
    "resources/list",
    "resources/templates/list",
    "resources/read",
    "resources/subscribe",
    "resources/unsubscribe",
    "subscriptions/listen",
)


def _session_key(ctx: Context) -> str:
    try:
        headers = ctx.headers
    except Exception:
        return _DEFAULT_SESSION
    if not headers:
        return _DEFAULT_SESSION
    sid = headers.get("mcp-session-id") or headers.get("MCP-Session-Id")
    return sid.strip() if isinstance(sid, str) and sid.strip() else _DEFAULT_SESSION


class _AncillaMCPServer(MCPServer):
    async def call_tool(self, name: str, arguments: dict, context: Context | None = None):
        if self._tool_manager.get_tool(name) is None:
            raise MCPError(code=INVALID_PARAMS, message=f"Unknown tool: {name}")
        return await super().call_tool(name, arguments, context)


def create_ancilla_mcp_server() -> MCPServer:
    histories: dict[str, list[dict[str, str]]] = {}
    hist_lock = threading.Lock()
    server = _AncillaMCPServer(
        "ancilla",
        instructions=INSTRUCTIONS,
        version="0.1.0",
    )

    @server.tool(
        name="ask_ancilla",
        description="Send a message to Ancilla and get her reply.",
        structured_output=False,
    )
    def ask_ancilla(message: str, ctx: Context) -> str:
        text = (message or "").strip()
        if not text:
            raise ValueError("message is required")
        key = _session_key(ctx)
        with hist_lock:
            history = histories.setdefault(key, [])
        runtime = get_runtime()
        runtime.preempt_for_interactive()
        try:
            answer, _emotion = run_agent_loop_with_tools(
                text,
                history,
                source="mcp",
            )
            append_and_trim(
                history,
                [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": answer},
                ],
                max_chars=_MAX_HISTORY_CHARS,
            )
            return answer
        finally:
            runtime.end()

    handlers = server._lowlevel_server._request_handlers
    for method in _NON_TOOL_METHODS:
        handlers.pop(method, None)
    return server


def run_stdio() -> None:
    create_ancilla_mcp_server().run(transport="stdio")


def run_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8767,
) -> None:
    logger.info("MCP HTTP http://{}:{}/mcp", host, port)
    create_ancilla_mcp_server().run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    run_stdio()
