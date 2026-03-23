"""
ツールレジストリ
"""

from datetime import datetime
from typing import Any, Callable

from ancilla_bot.batch.vector_store import search_summaries
from ancilla_bot.heartbeat.db import manage_state as heartbeat_manage_state
from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.tools.end_edge_session import end_edge_session
from ancilla_bot.tools.fetch_page import fetch_page
from ancilla_bot.tools.get_audio import get_audio
from ancilla_bot.tools.get_image import get_image
from ancilla_bot.tools.notify_user import notify_user
from ancilla_bot.tools.bash import bash as bash_impl
from ancilla_bot.tools.searxng_client import search as searxng_search
from ancilla_bot.tools.workspace_io import edit_file_safe as workspace_edit_file_safe
from ancilla_bot.tools.workspace_io import list_workspace as workspace_list_workspace
from ancilla_bot.tools.use_edgedevice import use_edgedevice
from ancilla_bot.tools.workspace_io import read_file as workspace_read_file
from ancilla_bot.tools.workspace_io import write_file as workspace_write_file

TOOL_DESCRIPTIONS: dict[str, str] = {
    # ── Information retrieval ─────────────────────────────────────────────
    "get_time": "Return current date/time. action_input: {}.",
    "web_search": (
        "Search the web via SearXNG. "
        "action_input: {\"query\": \"search terms\", \"max_results\": 5}. "
        "max_results optional (default 5)."
    ),
    "fetch_page": (
        "Fetch the main text of a web page (HTML stripped). "
        "action_input: {\"url\": \"https://example.com\", \"max_chars\": 8000}. "
        "max_chars optional. Only http/https; private IPs and localhost are rejected."
    ),
    # ── File operations ───────────────────────────────────────────────────
    "list_workspace": (
        "List files and directories inside workspace. "
        "action_input: {\"path\": \"\"}, optional {\"max_entries\": 100, \"max_depth\": 4}. "
        "Returns relative paths usable as-is in read_file."
    ),
    "read_file": (
        "Read a file inside workspace. "
        "action_input: {\"path\": \"NOTE.md\"}, optional {\"max_lines\": 2000}. "
        "Output is truncated at max_lines."
    ),
    "write_file": (
        "Overwrite a file inside workspace. "
        "action_input: {\"path\": \"NOTE.md\", \"content\": \"...\"}. "
        "Replaces the entire file. Use edit_file_safe for partial edits."
    ),
    "edit_file_safe": (
        "Append or partially replace a file (no full overwrite). "
        "operation=\"append\": {\"path\": \"...\", \"content\": \"...\"}. "
        "operation=\"replace\" (string): {\"path\": \"...\", \"old\": \"...\", \"new\": \"...\"}. "
        "operation=\"replace\" (lines): {\"path\": \"...\", \"start_line\": N, \"end_line\": M, \"new\": \"...\"} (1-based)."
    ),
    "bash": (
        "Run a shell command (cwd=workspace root). Returns stdout+stderr. "
        "action_input: {\"command\": \"ls -la\"}, optional {\"timeout_sec\": 60, \"stdin_text\": \"...\"}. "
        "timeout_sec default 60, max 300. Python also works: {\"command\": \"python script.py\"}."
    ),
    # ── Memory / state ────────────────────────────────────────────────────
    "search_memory": (
        "Vector-search past conversation summaries (long-term memory). "
        "action_input: {\"query\": \"search terms\", \"max_results\": 3}. "
        "Use when you need to recall previously discussed topics. max_results optional (default 3)."
    ),
    "manage_state": (
        "SQLite CRUD. "
        "table: user_tasks | agent_tasks | reminders | finances | interests | audit_log. "
        "operation: insert | select | update | delete. "
        "insert reminders/tasks: payload={\"scheduled_at\": \"YYYY-MM-DD HH:MM:SS\", \"content\": \"...\"}. "
        "insert finances: payload={\"amount\": -1200, \"category\": \"food\", \"memo\": \"...\", \"date\": \"YYYY-MM-DD\"}. "
        "insert interests: payload={\"name\": \"...\", \"description\": \"...\", \"url\": \"...\"}. "
        "select: payload={\"limit\": 10, \"completed\": false}. "
        "update: payload={\"id\": N, \"field\": value}. "
        "delete: payload={\"id\": N}. "
        "scheduled_at must be YYYY-MM-DD HH:MM:SS."
    ),
    # ── Notifications ─────────────────────────────────────────────────────
    "notify_user": (
        "Send a proactive notification to the user (via Discord). "
        "action_input: {\"message\": \"...\", \"title\": \"...\", "
        "\"source\": \"report|system|email\", \"level\": \"info|notice|warning|critical\"}. "
        "title, source, level are optional."
    ),
    # ── Edge device ───────────────────────────────────────────────────────
    "use_edgedevice": (
        "Switch to edge session to enable microphone and camera. "
        "action_input: {\"reason\": \"...\"} (optional). "
        "Use when the user wants to speak by voice or use the camera."
    ),
    "end_edge_session": (
        "End the edge session and return to main session. "
        "action_input: {}. "
        "Use when the agent has finished its edge-session goal."
    ),
    "get_image": (
        "Agent-initiated camera capture during an edge session. "
        "action_input: {\"reason\": \"...\", \"timeout_sec\": 60}. "
        "On success, the image is passed to the vision model in the next LLM turn. "
        "Requires an active edge session (use_edgedevice first)."
    ),
    "get_audio": (
        "Agent-initiated microphone capture during an edge session; returns STT text. "
        "action_input: {\"reason\": \"...\", \"timeout_sec\": 60}. "
        "Requires an active edge session (use_edgedevice first)."
    ),
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


def list_workspace(
    path: str = "",
    max_entries: int = 100,
    max_depth: int = 4,
    **kwargs: Any,
) -> str:
    """workspace 内のファイル・ディレクトリ一覧を返す。"""
    return workspace_list_workspace(
        path=path,
        max_entries=max_entries,
        max_depth=max_depth,
        **kwargs,
    )


def read_file(path: str, max_lines: int | None = None, **kwargs: Any) -> str:
    """workspace 内のファイルを読み込む。max_lines で行数制限（省略時 2000）。"""
    return workspace_read_file(path=path, max_lines=max_lines, **kwargs)


def edit_file_safe(
    path: str,
    operation: str,
    content: str | None = None,
    old: str | None = None,
    new: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    **kwargs: Any,
) -> str:
    """workspace 内のファイルに追記または置換（全上書きは禁止）。"""
    return workspace_edit_file_safe(
        path=path,
        operation=operation,
        content=content,
        old=old,
        new=new,
        start_line=start_line,
        end_line=end_line,
        **kwargs,
    )


def bash(
    command: str,
    timeout_sec: int = 60,
    stdin_text: str | None = None,
    **kwargs: Any,
) -> str:
    """シェルコマンドを workspace をカレントディレクトリとして実行する。"""
    return bash_impl(command=command, timeout_sec=timeout_sec, stdin_text=stdin_text, **kwargs)


def write_file(path: str, content: str, **kwargs: Any) -> str:
    """workspace 内のファイルに書き込む。"""
    return workspace_write_file(path=path, content=content, **kwargs)



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
    "list_workspace": list_workspace,
    "edit_file_safe": edit_file_safe,
    "bash": bash,
    "read_file": read_file,
    "write_file": write_file,
    "search_memory": search_memory,
    "manage_state": manage_state,
    "notify_user": notify_user,
    "end_edge_session": end_edge_session,
    "use_edgedevice": use_edgedevice,
    "get_image": get_image,
    "get_audio": get_audio,
}


def build_tools_system_prompt() -> str:
    """
    ツール呼び出し用の System メッセージを組み立てる。
    """
    tools_block = "\n".join(
        f"- {name}: {desc}" for name, desc in TOOL_DESCRIPTIONS.items()
    )
    return build_core_memory(tools_block)
