"""
Self-check:
1. クライアント: ミニマム stdio echo で initialize → tools/list → tools/call → shutdown
2. サーバ: Ancilla MCP Server で initialize → tools/list（ask_ancilla のみ）
tools/call ask_ancilla は LLM が必要なので行わない。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp.shared.exceptions import MCPError

from ancilla_bot.mcp.config import StdioServerConfig
from ancilla_bot.mcp.manager import McpManager

_ECHO_SERVER = """\
from mcp.server.mcpserver import MCPServer
server = MCPServer("echo", instructions="Echo")
@server.tool(name="echo", description="Echo text.", structured_output=False)
def echo(message: str) -> str:
    return message
if __name__ == "__main__":
    server.run(transport="stdio")
"""


def _check_client_echo() -> dict[str, object]:
    mgr = McpManager()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "echo.py"
        path.write_text(_ECHO_SERVER, encoding="utf-8")
        cfg = StdioServerConfig(name="echo", command=sys.executable, args=["-u", str(path)])
        mgr.start([cfg])
        try:
            names = [t.name for _, t in mgr.get_tools()]
            assert names == ["echo"], names
            result = mgr.call_tool("echo", "echo", {"message": "hi"})
            assert result == "hi", result
            return {"tools": names, "call": result}
        finally:
            mgr.shutdown()


def _check_ancilla_server() -> dict[str, object]:
    mgr = McpManager()
    cfg = StdioServerConfig(
        name="ancilla",
        command=sys.executable,
        args=["-m", "ancilla_bot.mcp.server"],
    )
    mgr.start([cfg])
    try:
        names = [t.name for _, t in mgr.get_tools()]
        assert names == ["ask_ancilla"], names
        with mgr._lock:
            caps = mgr._servers["ancilla"].capabilities
        assert caps.tools is not None
        assert caps.resources is None
        assert caps.prompts is None
        with mgr._lock:
            session = mgr._servers["ancilla"].session
        assert mgr._loop is not None
        fut = asyncio.run_coroutine_threadsafe(session.call_tool("nope", {}), mgr._loop)
        try:
            unexpected = fut.result(timeout=15)
        except Exception as exc:
            assert isinstance(exc, MCPError), type(exc)
            assert "Unknown tool" in str(exc), exc
        else:
            raise AssertionError(f"expected protocol error, got {unexpected!r}")
        return {"tools": names}
    finally:
        mgr.shutdown()


def main() -> int:
    client = _check_client_echo()
    server = _check_ancilla_server()
    print(json.dumps({"ok": True, "client": client, "server": server}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
