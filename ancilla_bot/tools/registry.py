"""
ツールレジストリ
"""

from datetime import datetime
from typing import Any, Callable

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.tools.searxng_client import search as searxng_search
from ancilla_bot.tools.workspace_io import read_file as workspace_read_file
from ancilla_bot.tools.workspace_io import write_file as workspace_write_file

# プロンプト用のツール説明
TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_time": "現在の日時を返す。action_input は {} でよい。",
    "web_search": "Web を検索する。action_input は {\"query\": \"検索クエリ\", \"max_results\": 5} の形。max_results は省略可（デフォルト 5）。",
    "read_file": "workspace 内のファイルを読み込む。action_input は {\"path\": \"memory/NOTE.md\"} の形。",
    "write_file": "workspace 内のファイルに書き込む。action_input は {\"path\": \"memory/NOTE.md\", \"content\": \"内容\"} の形。",
    "update_memory": "主記憶の USER.md または AGENT.md を書き換える。action_input は {\"file\": \"USER\" または \"AGENT\", \"content\": \"書き込む内容\"}。過度に呼ばないこと。",
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
    path = f"memory/{file.upper()}.md"
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
