"""
ツールレジストリ
"""

from datetime import datetime
from typing import Any, Callable

from ancilla_bot.batch.vector_store import search_summaries
from ancilla_bot.heartbeat.db import manage_state as heartbeat_manage_state
from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.tools.fetch_page import fetch_page
from ancilla_bot.tools.notify_user import notify_user
from ancilla_bot.tools.searxng_client import search as searxng_search
from ancilla_bot.tools.workspace_io import read_file as workspace_read_file
from ancilla_bot.tools.workspace_io import write_file as workspace_write_file

# Tool descriptions for prompt (English)
TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_time": "Return current date/time. action_input: {}.",
    "web_search": "Search the web. action_input: {\"query\": \"search query\", \"max_results\": 5}. max_results optional (default 5).",
    "fetch_page": "Get the main text of a web page. action_input: {\"url\": \"https://example.com/page\", \"max_chars\": 8000}. max_chars optional (default from config). Only http/https URLs are allowed.",
    "read_file": "Read a file in workspace. action_input: {\"path\": \"NOTE.md\"}.",
    "write_file": "Write to a file in workspace. action_input: {\"path\": \"NOTE.md\", \"content\": \"content\"}.",
    "update_memory": "Update USER.md or AGENT.md. action_input: {\"file\": \"USER\" or \"AGENT\", \"content\": \"content\"}. Use sparingly.",
    "search_memory": "Search past conversation summaries (long-term memory). action_input: {\"query\": \"search query\", \"max_results\": 3}. max_results optional (default 3). Use when you need to recall past topics.",
    "manage_state": "SQLite CRUD: table (user_tasks|agent_tasks|reminders|finances|interests|audit_log), operation (insert|select|update|delete), payload (dict). insert tasks/reminders: {scheduled_at, content}. insert finances: {amount, category, memo?, date?}. insert interests: {name}, optional {description, status, url}. select: {limit?, completed?} for tasks/reminders, {limit} for others. update: {id, ...fields}. delete: {id}.",
    "notify_user": "Send a proactive notification to the user via Discord. action_input: {\"message\": \"text\", \"source\": \"system|report|email\", \"level\": \"info|notice|warning|critical\", \"title\": \"optional title\"}. source optional (default \"report\"), level optional (default \"info\").",
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


def search_memory(query: str, max_results: int = 3, **kwargs: Any) -> str:
    """
    長期記憶（要約）をベクトル検索する
    action_input: {"query": "検索クエリ", "max_results": 3}
    """
    _ = kwargs
    results = search_summaries(query, n_results=max_results)
    if not results:
        return "No matching past summaries found."
    max_chars_per = 400
    parts = []
    for i, item in enumerate(results, 1):
        doc = (item.get("document") or "")[:max_chars_per]
        if len(item.get("document") or "") > max_chars_per:
            doc += "..."
        parts.append(f"[{i}] {doc}")
    return "\n\n".join(parts)


def manage_state(table: str, operation: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> str:
    """SQLite の CRUD。table, operation, payload でテーブル・操作・引数を指定。"""
    _ = kwargs
    return heartbeat_manage_state(table=table, operation=operation, payload=payload or {})


TOOL_REGISTRY: dict[str, Callable[..., str]] = {
    "get_time": get_time,
    "web_search": web_search,
    "fetch_page": fetch_page,
    "read_file": read_file,
    "write_file": write_file,
    "update_memory": update_memory,
    "search_memory": search_memory,
    "manage_state": manage_state,
    "notify_user": notify_user,
}


def build_tools_system_prompt() -> str:
    """
    ツール呼び出し用の System メッセージを組み立てる。
    """
    tools_block = "\n".join(
        f"- {name}: {desc}" for name, desc in TOOL_DESCRIPTIONS.items()
    )
    return build_core_memory(tools_block)
