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
    # ── 情報取得 ──────────────────────────────────────────────────────────
    "get_time": (
        "現在の日時を返す。action_input: {}."
    ),
    "web_search": (
        "SearXNG でウェブ検索する。"
        "action_input: {\"query\": \"検索クエリ\", \"max_results\": 5}. "
        "max_results は省略可（デフォルト 5）。"
    ),
    "fetch_page": (
        "URL のページ本文テキストを取得する（HTML 除去済み）。"
        "action_input: {\"url\": \"https://example.com\", \"max_chars\": 8000}. "
        "max_chars 省略可。http/https のみ。プライベート IP・localhost は拒否。"
    ),
    # ── ファイル操作 ──────────────────────────────────────────────────────
    "list_workspace": (
        "workspace 内のファイル・ディレクトリ一覧を返す。"
        "action_input: {\"path\": \"\"}, optional {\"max_entries\": 100, \"max_depth\": 4}. "
        "返されるパスは workspace からの相対パス。read_file の path にそのまま使える。"
    ),
    "read_file": (
        "workspace 内のファイルを読む。"
        "action_input: {\"path\": \"NOTE.md\"}, optional {\"max_lines\": 2000}. "
        "max_lines を超えた場合は切り詰め。"
    ),
    "write_file": (
        "workspace 内のファイルに全上書き保存する。"
        "action_input: {\"path\": \"NOTE.md\", \"content\": \"内容\"}. "
        "既存ファイルは完全に置き換わる。部分的な変更には edit_file_safe を使うこと。"
    ),
    "edit_file_safe": (
        "既存ファイルへの追記または部分置換（全上書き禁止）。"
        "operation=\"append\": {\"path\": \"...\", \"content\": \"追記内容\"}. "
        "operation=\"replace\" (文字列): {\"path\": \"...\", \"old\": \"旧文字列\", \"new\": \"新文字列\"}. "
        "operation=\"replace\" (行範囲): {\"path\": \"...\", \"start_line\": N, \"end_line\": M, \"new\": \"内容\"} (1-based)."
    ),
    "bash": (
        "シェルコマンドを実行して stdout+stderr を返す（cwd=workspace ルート）。"
        "action_input: {\"command\": \"ls -la\"}, optional {\"timeout_sec\": 60, \"stdin_text\": \"...\"}. "
        "timeout_sec デフォルト 60、最大 300。Python 実行も可: {\"command\": \"python script.py\"}."
    ),
    # ── 記憶・状態管理 ────────────────────────────────────────────────────
    "search_memory": (
        "過去の会話要約をベクトル検索する（長期記憶）。"
        "action_input: {\"query\": \"検索クエリ\", \"max_results\": 3}. "
        "過去に話した内容を思い出したいときに使う。max_results 省略可（デフォルト 3）。"
    ),
    "manage_state": (
        "SQLite の CRUD 操作。"
        "table: user_tasks | agent_tasks | reminders | finances | interests | audit_log. "
        "operation: insert | select | update | delete. "
        "insert reminders/tasks: payload={\"scheduled_at\": \"YYYY-MM-DD HH:MM:SS\", \"content\": \"内容\"}. "
        "insert finances: payload={\"amount\": 1000, \"category\": \"food\", \"memo\": \"...\", \"date\": \"YYYY-MM-DD\"}. "
        "insert interests: payload={\"name\": \"名称\", \"description\": \"...\", \"url\": \"...\"}. "
        "select: payload={\"limit\": 10, \"completed\": false}. "
        "update: payload={\"id\": N, \"content\": \"新内容\"}. "
        "delete: payload={\"id\": N}. "
        "注意: scheduled_at は必ず YYYY-MM-DD HH:MM:SS 形式で指定すること。"
    ),
    # ── 通知 ──────────────────────────────────────────────────────────────
    "notify_user": (
        "ユーザーへ通知を送る（Discord 経由）。"
        "action_input: {\"message\": \"本文\", \"title\": \"タイトル\", "
        "\"source\": \"report|system|email\", \"level\": \"info|notice|warning|critical\"}. "
        "title・source・level は省略可。重要な報告や完了通知に使う。"
    ),
    # ── エッジデバイス ────────────────────────────────────────────────────
    "use_edgedevice": (
        "エッジセッションへ切り替える（マイク・カメラを有効化）。"
        "action_input: {\"reason\": \"理由\"} (省略可). "
        "ユーザーが音声で話したい・カメラを使いたいと言ったときに使う。"
    ),
    "end_edge_session": (
        "エッジセッションを終了してメインセッションに戻る。"
        "action_input: {}. "
        "エージェントがエッジセッションの目的を達成したと判断したときに使う。"
    ),
    "get_image": (
        "エッジセッション中にカメラ画像を取得する（エージェント主導）。"
        "action_input: {\"reason\": \"取得理由\", \"timeout_sec\": 60}. "
        "取得成功後、次のターンでビジョンモデルに画像が渡される。"
        "use_edgedevice でエッジセッションに入っていること。"
    ),
    "get_audio": (
        "エッジセッション中にマイク音声を録音して STT テキストを返す（エージェント主導）。"
        "action_input: {\"reason\": \"取得理由\", \"timeout_sec\": 60}. "
        "返り値は音声認識テキスト。use_edgedevice でエッジセッションに入っていること。"
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
