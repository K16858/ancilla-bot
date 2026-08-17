"""
Self-check: stdio Ancilla MCP Server で initialize → tools/list。
tools/call は LLM が必要なので行わない。
"""

from __future__ import annotations

import json
import sys

from ancilla_bot.mcp.config import StdioServerConfig
from ancilla_bot.mcp.manager import McpManager


def main() -> int:
    mgr = McpManager()
    cfg = StdioServerConfig(
        name="ancilla",
        command=sys.executable,
        args=["-m", "ancilla_bot.mcp.server"],
    )
    mgr.start([cfg])
    try:
        tools = mgr.get_tools()
        names = [t.name for _, t in tools]
        assert "ask_ancilla" in names, names
        assert names == ["ask_ancilla"], names
        print(json.dumps({"ok": True, "tools": names}, ensure_ascii=False))
        return 0
    finally:
        mgr.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
