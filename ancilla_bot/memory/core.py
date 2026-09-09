"""
主記憶（Core Memory）：CHARACTER / AGENT / USER / TOOLS を Markdown から読み込み、
注入順で連結してプロンプトを組み立てる
"""

from __future__ import annotations

import os
from pathlib import Path

from ancilla_bot.skills.loader import format_skills_catalog
from ancilla_bot.mcp.catalog import format_mcp_catalog

from ancilla_bot.cli.paths import get_workspace
from ancilla_bot.runtime.mode import format_mode_overlay
from ancilla_bot.runtime.self_model import format_runtime_self_model

DEFAULT_PROMPTS_DIR = Path(os.getenv("ANCILLA_PROMPTS_DIR", "data/prompts"))


def _load_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _section(content: str, title: str | None = None) -> str:
    if not content.strip():
        return ""
    if title:
        return f"\n\n## {title}\n\n{content}"
    return f"\n\n{content}"


def build_character_prompt() -> str:
    """CHARACTER.md + USER.md のみ（ツール・エージェント指示なし）。
    ReAct JSON 形式を使わない自由応答用システムプロンプト。"""
    prompts = DEFAULT_PROMPTS_DIR
    workspace = get_workspace()

    character = _load_file(prompts / "CHARACTER.md")
    user      = _load_file(workspace / "USER.md")

    parts: list[str] = []
    if character:
        parts.append(character.strip())
    if user:
        parts.append(_section(user, None))

    result = "\n\n".join(p.strip() for p in parts if p.strip())
    return result or "You are a helpful assistant."


def build_core_memory(tools_block: str) -> str:
    """
    主記憶を組み立てる。注入順: CHARACTER → USER → Mode → Runtime Self Model → AGENT → tools → skills → MCP。
    ツール一覧の正本は tools_block（Capability / registry）。TOOLS.md は使わない。
    """
    prompts = DEFAULT_PROMPTS_DIR
    workspace = get_workspace()
    from ancilla_bot.llm.tool_adapter import is_native_tool_mode

    native = is_native_tool_mode()

    agent_name = "AGENT.native.md" if native else "AGENT.md"
    agent = _load_file(workspace / agent_name)
    from ancilla_bot.core.run_context import run_source

    include_user = run_source.get() != "idle_reflection"
    user = _load_file(workspace / "USER.md") if include_user else ""
    character = _load_file(prompts / "CHARACTER.md")

    parts: list[str] = []
    if character:
        parts.append(character.strip())
    if user:
        parts.append(_section(user, None))
    overlay = format_mode_overlay()
    if overlay:
        parts.append(_section(overlay, None))
    self_model = format_runtime_self_model()
    if self_model:
        parts.append(_section(self_model, None))
    if agent:
        parts.append(_section(agent, None))
    parts.append(_section(tools_block, None))

    catalog = format_skills_catalog()
    if catalog:
        parts.append(_section(catalog, None))

    mcp_catalog = format_mcp_catalog()
    if mcp_catalog:
        parts.append(_section(mcp_catalog, None))

    result = "\n".join(p.strip() for p in parts if p.strip())
    if not result:
        if native:
            return (
                "You are a helpful assistant. Respond in plain Japanese. "
                "Use tools when needed.\n\n## Available tools\n\n" + tools_block
            )
        return (
            "You are an assistant that outputs thought and tool calls or final_answer in JSON format.\n\n"
            "## Available tools\n\n" + tools_block
        )
    return result
