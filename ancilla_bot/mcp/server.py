"""
Ancilla を MCP Server として公開する。外部には ask_ancilla のみ。
"""

from __future__ import annotations

import threading
from loguru import logger
from mcp.server.mcpserver import Context, MCPServer

from ancilla_bot.core.agent_loop import run_agent_loop_with_tools
from ancilla_bot.llm.context_window import resolve_max_history_chars
from ancilla_bot.memory.short_term import append_and_trim

INSTRUCTIONS = "Talk to Ancilla. Pass the user's message in the message argument."
_MAX_HISTORY_CHARS = resolve_max_history_chars()
_DEFAULT_SESSION = "default"


def _session_key(ctx: Context) -> str:
    try:
        headers = ctx.headers
    except Exception:
        return _DEFAULT_SESSION
    if not headers:
        return _DEFAULT_SESSION
    sid = headers.get("mcp-session-id") or headers.get("MCP-Session-Id")
    return sid.strip() if isinstance(sid, str) and sid.strip() else _DEFAULT_SESSION


def create_ancilla_mcp_server(
    *,
    agent_lock: threading.Lock | None = None,
) -> MCPServer:
    histories: dict[str, list[dict[str, str]]] = {}
    hist_lock = threading.Lock()
    server = MCPServer(
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
        if agent_lock is not None and not agent_lock.acquire(blocking=False):
            return "バックグラウンド処理中です。しばらくお待ちください。"
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
            if agent_lock is not None:
                agent_lock.release()

    return server


def run_stdio(agent_lock: threading.Lock | None = None) -> None:
    create_ancilla_mcp_server(agent_lock=agent_lock).run(transport="stdio")


def run_http(
    *,
    host: str = "127.0.0.1",
    port: int = 8767,
    agent_lock: threading.Lock | None = None,
) -> None:
    logger.info("MCP HTTP http://{}:{}/mcp", host, port)
    create_ancilla_mcp_server(agent_lock=agent_lock).run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )
