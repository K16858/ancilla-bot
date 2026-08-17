"""MCP カタログ（instructions / tools / resources / prompts）をプロンプト用に整形。"""

from __future__ import annotations

from ancilla_bot.mcp.bridge import namespaced_tool_name
from ancilla_bot.mcp.manager import get_manager


def format_mcp_catalog() -> str:
    mgr = get_manager()
    if not mgr.list_server_names():
        return ""

    sections: list[str] = ["## MCP", ""]

    instructions = mgr.get_instructions()
    if instructions:
        sections.append("### Server instructions")
        for name, text in sorted(instructions.items()):
            sections.append(f"- {name}: {text}")
        sections.append("")

    tools = mgr.get_tools()
    if tools:
        sections.append("### MCP tools")
        for server, tool in tools:
            full = namespaced_tool_name(server, tool.name)
            desc = tool.description or "(no description)"
            sections.append(f"- {full}: {desc}")
        sections.append("")

    resources = mgr.get_resources()
    if resources:
        sections.append("### MCP resources")
        for server, res in resources:
            desc = f" — {res.description}" if res.description else ""
            sections.append(f"- [{server}] {res.uri} ({res.name}){desc}")
        sections.append("")

    prompts = mgr.get_prompts()
    if prompts:
        sections.append("### MCP prompts")
        for server, prompt in prompts:
            desc = f" — {prompt.description}" if prompt.description else ""
            sections.append(f"- [{server}] {prompt.name}{desc}")
        sections.append("")

    text = "\n".join(sections).rstrip()
    return text if text != "## MCP" else ""
