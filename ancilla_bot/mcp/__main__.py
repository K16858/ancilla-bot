"""
Self-check: spawn a minimal stdio MCP server, list tools, call echo, shutdown.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path

from ancilla_bot.mcp.config import StdioServerConfig
from ancilla_bot.mcp.manager import McpManager


def _write_echo_server(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            from mcp.server.mcpserver import MCPServer

            server = MCPServer("ancilla-echo", instructions="Echo server for ancilla self-check.")

            @server.tool()
            def echo(message: str) -> str:
                \"\"\"Echo the message back.\"\"\"
                return message

            if __name__ == "__main__":
                server.run(transport="stdio")
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        server_py = Path(tmp) / "echo_server.py"
        _write_echo_server(server_py)
        mgr = McpManager()
        cfg = StdioServerConfig(
            name="echo",
            command=sys.executable,
            args=[str(server_py)],
        )
        mgr.start([cfg])
        try:
            tools = mgr.get_tools()
            names = [t.name for _, t in tools]
            assert "echo" in names, names
            result = mgr.call_tool("echo", "echo", {"message": "ping"})
            assert "ping" in result, result
            catalog_tools = {f"{s}__{t.name}" for s, t in tools}
            assert "echo__echo" in catalog_tools
            print(json.dumps({"ok": True, "tools": names, "result": result}, ensure_ascii=False))
            return 0
        finally:
            mgr.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
