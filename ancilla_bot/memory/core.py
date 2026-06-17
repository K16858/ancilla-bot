"""
主記憶（Core Memory）：CHARACTER / AGENT / USER / TOOLS を Markdown から読み込み、
注入順で連結してプロンプトを組み立てる
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PROMPTS_DIR = Path(os.getenv("ANCILLA_PROMPTS_DIR", "data/prompts"))
DEFAULT_WORKSPACE_DIR = Path(os.getenv("ANCILLA_WORKSPACE_DIR", "workspace"))


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
    workspace = DEFAULT_WORKSPACE_DIR

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
    主記憶を組み立てる。注入順: CHARACTER → AGENT → USER → TOOLS。

    Args:
        tools_block: 利用可能なツールの説明（registry から生成。TOOLS.md が無いときに使う）。

    Returns:
        system プロンプトとして使う文字列。
    """
    prompts = DEFAULT_PROMPTS_DIR
    workspace = DEFAULT_WORKSPACE_DIR
    from ancilla_bot.llm.tool_adapter import is_native_tool_mode

    native = is_native_tool_mode()

    agent_name = "AGENT.native.md" if native else "AGENT.md"
    tools_name = "TOOLS.native.md" if native else "TOOLS.md"
    agent = _load_file(workspace / agent_name)
    user = _load_file(workspace / "USER.md")
    tools_md = _load_file(prompts / tools_name)
    character = _load_file(prompts / "CHARACTER.md")

    tools_content = tools_md if tools_md else tools_block

    parts: list[str] = []
    if character:
        parts.append(character.strip())
    if user:
        parts.append(_section(user, None))
    if agent:
        parts.append(_section(agent, None))
    parts.append(_section(tools_content, None))

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
