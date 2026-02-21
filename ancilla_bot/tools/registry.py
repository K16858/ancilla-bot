"""
ツールレジストリ
"""

from datetime import datetime
from typing import Any, Callable

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.tools.searxng_client import search as searxng_search
from ancilla_bot.tools.workspace_io import read_file as workspace_read_file
from ancilla_bot.tools.workspace_io import write_file as workspace_write_file

# Tool descriptions for prompt (English)
TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_time": "Return current date/time. action_input: {}.",
    "web_search": "Search the web. action_input: {\"query\": \"search query\", \"max_results\": 5}. max_results optional (default 5).",
    "read_file": "Read a file in workspace. action_input: {\"path\": \"NOTE.md\"}.",
    "write_file": "Write to a file in workspace. action_input: {\"path\": \"NOTE.md\", \"content\": \"content\"}.",
    "update_memory": "Update USER.md or AGENT.md. action_input: {\"file\": \"USER\" or \"AGENT\", \"content\": \"content\"}. Use sparingly.",
}


def get_time(**kwargs: Any) -> str:
    """
    現在の日時を返す。action_input は {} でよい。
    """
    _ = kwargs
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def web_search(query: str, max_results: int = 5, **kwargs: Any) -> str:
    """
    SearXNG で Web 検索を行う。
    action_input: {"query": "検索クエリ", "max_results": 5}
    """
    _ = kwargs
    return searxng_search(
        query=query,
        max_results=max_results,
        format_structured=True,
        content_max_chars=300,
    )


def read_file(path: str, **kwargs: Any) -> str:
    """workspace 内のファイルを読み込む。"""
    return workspace_read_file(path=path, **kwargs)


def write_file(path: str, content: str, **kwargs: Any) -> str:
    """workspace 内のファイルに書き込む。"""
    return workspace_write_file(path=path, content=content, **kwargs)


def update_memory(file: str, content: str, **kwargs: Any) -> str:
    """
    workspace/memory の USER.md または AGENT.md を書き換える。
    file: "USER" または "AGENT"
    """
    _ = kwargs
    if file.upper() not in ("USER", "AGENT"):
        return "Error: file は USER または AGENT のいずれかを指定してください。"
    path = f"{file.upper()}.md"
    return workspace_write_file(path=path, content=content)


TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "get_time": get_time,
    "web_search": web_search,
    "read_file": read_file,
    "write_file": write_file,
    "update_memory": update_memory,
}


def build_tools_system_prompt() -> str:
    """
    ツール呼び出し用の System メッセージを組み立てる。
    主記憶（CHARACTER → AGENT → USER → TOOLS）を連結して返す。
    """
    tools_block = "\n".join(
        f"- {name}: {desc}" for name, desc in TOOL_DESCRIPTIONS.items()
    )
    return build_core_memory(tools_block)
