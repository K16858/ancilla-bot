"""
SQLite: user_tasks, agent_tasks, reminders, finances, interests, audit_log。
ツールは manage_state 1 本で CRUD。Heartbeat 用は get_due_* / mark_* を利用。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_CONVERSATION_DIR = Path(
    os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation")
)

# ツールから操作可能なテーブル（ホワイトリスト）
ALLOWED_TABLES = ("user_tasks", "agent_tasks", "reminders", "finances", "interests", "audit_log")


def get_db_path() -> Path:
    """Heartbeat 用 DB ファイルのパス。ANCILLA_CONVERSATION_DIR 配下の ancilla.db。"""
    return DEFAULT_CONVERSATION_DIR / "ancilla.db"


def _conn() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


_SCHEMA_USER_TASKS = """
CREATE TABLE IF NOT EXISTS user_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_at TEXT NOT NULL,
    content TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

_SCHEMA_AGENT_TASKS = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_at TEXT NOT NULL,
    content TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'heartbeat',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
)
"""

# 既存 DB への後付けマイグレーション（カラムが無ければ追加）
_MIGRATE_AGENT_TASKS_SOURCE = (
    "ALTER TABLE agent_tasks ADD COLUMN source TEXT NOT NULL DEFAULT 'heartbeat'"
)
_MIGRATE_AGENT_TASKS_STATUS = (
    "ALTER TABLE agent_tasks ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
)

_SCHEMA_REMINDERS = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_at TEXT NOT NULL,
    content TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

_SCHEMA_FINANCES = """
CREATE TABLE IF NOT EXISTS finances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL,
    category TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""

_SCHEMA_INTERESTS = """
CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'interested',
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

_SCHEMA_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    args_summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

_SCHEMA_AGENT_RUNS = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    user_input TEXT NOT NULL,
    parent_run_id TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
)
"""

_SCHEMA_AGENT_RUN_STEPS = """
CREATE TABLE IF NOT EXISTS agent_run_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    status TEXT NOT NULL,
    thought TEXT NOT NULL DEFAULT '',
    action TEXT,
    action_input_json TEXT NOT NULL DEFAULT '{}',
    observation TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(run_id) REFERENCES agent_runs(id)
)
"""


def ensure_schema() -> None:
    """全テーブルがなければ作成する。既存テーブルへのマイグレーションも実行。"""
    with _conn() as c:
        c.executescript(_SCHEMA_USER_TASKS)
        c.executescript(_SCHEMA_AGENT_TASKS)
        c.executescript(_SCHEMA_REMINDERS)
        c.executescript(_SCHEMA_FINANCES)
        c.executescript(_SCHEMA_INTERESTS)
        c.executescript(_SCHEMA_AUDIT_LOG)
        c.executescript(_SCHEMA_AGENT_RUNS)
        c.executescript(_SCHEMA_AGENT_RUN_STEPS)
        # agent_tasks.source カラムが既存 DB に無ければ追加
        try:
            c.execute(_MIGRATE_AGENT_TASKS_SOURCE)
        except Exception:
            pass  # カラムが既にあれば無視
        # agent_tasks.status カラムが既存 DB に無ければ追加
        try:
            c.execute(_MIGRATE_AGENT_TASKS_STATUS)
        except Exception:
            pass  # カラムが既にあれば無視


def append_audit_log(tool_name: str, args_summary: str = "") -> None:
    """ランタイム用: ツール呼び出し + 引数を記録。"""
    try:
        ensure_schema()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        s = (args_summary or "")[:500]
        with _conn() as c:
            c.execute(
                "INSERT INTO audit_log (tool_name, args_summary, created_at) VALUES (?, ?, ?)",
                (tool_name.strip() or "unknown", s, now),
            )
    except Exception:
        pass


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    names = [d[0] for d in cursor.description]
    return dict(zip(names, row))


def create_agent_run(
    run_id: str,
    *,
    source: str,
    user_input: str,
    parent_run_id: str | None = None,
) -> None:
    ensure_schema()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        c.execute(
            "INSERT INTO agent_runs "
            "(id, status, source, user_input, parent_run_id, created_at, updated_at) "
            "VALUES (?, 'running', ?, ?, ?, ?, ?)",
            (run_id, source, user_input, parent_run_id, now, now),
        )


def update_agent_run_status(
    run_id: str,
    status: str,
    *,
    last_error: str = "",
) -> None:
    ensure_schema()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    completed_at = now if status in {"completed", "failed", "cancelled", "max_turns"} else None
    with _conn() as c:
        c.execute(
            "UPDATE agent_runs "
            "SET status = ?, last_error = ?, updated_at = ?, completed_at = ? "
            "WHERE id = ?",
            (status, last_error, now, completed_at, run_id),
        )


def create_agent_run_step(
    run_id: str,
    *,
    turn_index: int,
    status: str,
    thought: str = "",
    action: str | None = None,
    action_input: dict[str, Any] | None = None,
) -> int:
    ensure_schema()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action_input_json = json.dumps(action_input or {}, ensure_ascii=False, default=str)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO agent_run_steps "
            "(run_id, turn_index, status, thought, action, action_input_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, turn_index, status, thought, action, action_input_json, now),
        )
        return int(cur.lastrowid)


def complete_agent_run_step(
    step_id: int,
    status: str,
    *,
    observation: str = "",
    error: str = "",
) -> None:
    ensure_schema()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        c.execute(
            "UPDATE agent_run_steps "
            "SET status = ?, observation = ?, error = ?, completed_at = ? "
            "WHERE id = ?",
            (status, observation, error, now, step_id),
        )


def list_agent_runs(limit: int = 20) -> list[dict[str, Any]]:
    ensure_schema()
    with _conn() as c:
        cur = c.execute(
            "SELECT id, status, source, user_input, parent_run_id, last_error, "
            "created_at, updated_at, completed_at "
            "FROM agent_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def get_agent_run(run_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with _conn() as c:
        cur = c.execute(
            "SELECT id, status, source, user_input, parent_run_id, last_error, "
            "created_at, updated_at, completed_at "
            "FROM agent_runs WHERE id = ?",
            (run_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(cur, row) if row else None


def list_agent_run_steps(run_id: str) -> list[dict[str, Any]]:
    ensure_schema()
    with _conn() as c:
        cur = c.execute(
            "SELECT id, run_id, turn_index, status, thought, action, action_input_json, "
            "observation, error, created_at, completed_at "
            "FROM agent_run_steps WHERE run_id = ? ORDER BY turn_index ASC, id ASC",
            (run_id,),
        )
        return [_row_to_dict(cur, row) for row in cur.fetchall()]


def _get_due_from_table(table: str, *, at: datetime | None = None) -> list[dict[str, Any]]:
    """共通: 指定テーブルから due 行を取得（tasks 系・reminders 用）。
    agent_tasks は source='heartbeat' のみ取得（source='self' は heartbeat で発火しない）。
    """
    at = at or datetime.now()
    ts = at.strftime("%Y-%m-%d %H:%M:%S")
    ensure_schema()
    with _conn() as conn:
        if table == "agent_tasks":
            cur = conn.execute(
                "SELECT id, scheduled_at, content, completed, source, created_at FROM agent_tasks "
                "WHERE datetime(scheduled_at) <= datetime(?) AND completed = 0 AND source = 'heartbeat' "
                "ORDER BY scheduled_at ASC",
                (ts,),
            )
        else:
            cur = conn.execute(
                f"SELECT id, scheduled_at, content, completed, created_at FROM {table} "
                "WHERE datetime(scheduled_at) <= datetime(?) AND completed = 0 ORDER BY scheduled_at ASC",
                (ts,),
            )
        rows = cur.fetchall()
        results = [_row_to_dict(cur, r) for r in rows]
        for r in results:
            r["_table"] = table
        return results


def get_due_tasks(*, at: datetime | None = None) -> list[dict[str, Any]]:
    """
    実行予定時刻 <= at かつ未完了の user_tasks / agent_tasks をまとめて返す。
    at 省略時は現在時刻。0 件なら LLM に触れず return する用途。
    """
    tasks: list[dict[str, Any]] = []
    tasks.extend(_get_due_from_table("user_tasks", at=at))
    tasks.extend(_get_due_from_table("agent_tasks", at=at))
    return tasks


def get_due_reminders(*, at: datetime | None = None) -> list[dict[str, Any]]:
    """
    実行予定時刻 <= at かつ未完了の reminders を返す。
    at 省略時は現在時刻。
    """
    return _get_due_from_table("reminders", at=at)


def has_due_work(*, at: datetime | None = None) -> bool:
    """いま実行すべきタスクまたはリマインダーが 1 件以上あるか。"""
    tasks = get_due_tasks(at=at)
    reminders = get_due_reminders(at=at)
    return len(tasks) > 0 or len(reminders) > 0


def mark_user_tasks_completed(task_ids: list[int]) -> None:
    """指定した user_tasks id を完了済みにする。"""
    if not task_ids:
        return
    ensure_schema()
    with _conn() as c:
        placeholders = ",".join("?" * len(task_ids))
        c.execute(
            f"UPDATE user_tasks SET completed = 1 WHERE id IN ({placeholders})",
            task_ids,
        )


def mark_agent_tasks_completed(task_ids: list[int]) -> None:
    """指定した agent_tasks id を完了済みにする。"""
    if not task_ids:
        return
    ensure_schema()
    with _conn() as c:
        placeholders = ",".join("?" * len(task_ids))
        c.execute(
            f"UPDATE agent_tasks SET completed = 1 WHERE id IN ({placeholders})",
            task_ids,
        )


def mark_reminders_completed(reminder_ids: list[int]) -> None:
    """指定した reminder id を完了済みにする。Heartbeat が ReAct に渡した後にスクリプト側で呼ぶ。"""
    if not reminder_ids:
        return
    ensure_schema()
    with _conn() as c:
        placeholders = ",".join("?" * len(reminder_ids))
        c.execute(
            f"UPDATE reminders SET completed = 1 WHERE id IN ({placeholders})",
            reminder_ids,
        )


def _normalize_scheduled_at(value: str) -> str:
    """日時文字列を 'YYYY-MM-DD HH:MM:SS' に正規化する。ISO 8601 の T 区切りも処理する。"""
    s = (value or "").strip()
    # datetime.fromisoformat は T・スペース両対応（Python 3.11+）
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return s  # パース不能な場合はそのまま返す


def _validate_insert_payload(table: str, payload: dict[str, Any]) -> str | None:
    """insert 用 payload を検証。エラー時はメッセージ、OK 時は None。"""
    if table in ("user_tasks", "agent_tasks", "reminders"):
        if not (payload.get("scheduled_at") and payload.get("content")):
            return "Error: tasks/reminders require scheduled_at and content."
        return None
    if table == "finances":
        if "amount" not in payload or "category" not in payload:
            return "Error: finances require amount and category. memo and date are optional."
        return None
    if table == "interests":
        if not payload.get("name"):
            return "Error: interests require name. description, status, url are optional."
        return None
    if table == "audit_log":
        if not payload.get("tool_name"):
            return "Error: audit_log requires tool_name. args_summary optional."
        return None
    return "Error: unknown table."


def manage_state(
    table: str,
    operation: str,
    payload: dict[str, Any] | None = None,
) -> str:
    """
    SQLite の CRUD。テーブルはホワイトリストのみ。
    table: user_tasks | agent_tasks | reminders | finances | interests | audit_log
    operation: insert | select | update | delete
    payload: 操作ごとの引数。insert は行データ、select は limit/条件、update は id+更新項目、delete は id。
    """
    payload = payload or {}
    table = (table or "").strip().lower()
    operation = (operation or "").strip().lower()
    if table not in ALLOWED_TABLES:
        return f"Error: table must be one of {list(ALLOWED_TABLES)}."
    if operation not in ("insert", "select", "update", "delete"):
        return "Error: operation must be insert, select, update, or delete."
    ensure_schema()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with _conn() as conn:
            c = conn.cursor()
            if operation == "insert":
                err = _validate_insert_payload(table, payload)
                if err:
                    return err
                if table in ("user_tasks", "agent_tasks", "reminders"):
                    scheduled_at = _normalize_scheduled_at(str(payload.get("scheduled_at", "")))
                    content = str(payload.get("content", "")).strip()
                    if not content:
                        return "Error: content is required."
                    if table == "agent_tasks":
                        raw_source = str(payload.get("source", "heartbeat")).strip().lower()
                        source = raw_source if raw_source in ("heartbeat", "self") else "heartbeat"
                        raw_status = str(payload.get("status", "pending")).strip().lower()
                        status = raw_status if raw_status in ("pending", "in_progress", "completed", "cancelled") else "pending"
                        c.execute(
                            "INSERT INTO agent_tasks (scheduled_at, content, completed, source, status, created_at) VALUES (?, ?, 0, ?, ?, ?)",
                            (scheduled_at, content, source, status, now),
                        )
                    else:
                        c.execute(
                            f"INSERT INTO {table} (scheduled_at, content, completed, created_at) VALUES (?, ?, 0, ?)",
                            (scheduled_at, content, now),
                        )
                elif table == "finances":
                    amount = float(payload.get("amount", 0))
                    category = str(payload.get("category", "")).strip() or "other"
                    memo = str(payload.get("memo", "")).strip()
                    date = str(payload.get("date", "")).strip() or now[:10]
                    c.execute(
                        "INSERT INTO finances (amount, category, memo, date, created_at) VALUES (?, ?, ?, ?, ?)",
                        (amount, category, memo, date, now),
                    )
                elif table == "interests":
                    name = str(payload.get("name", "")).strip()
                    if not name:
                        return "Error: name is required."
                    description = str(payload.get("description", "")).strip()[:2000]
                    status = str(payload.get("status", "")).strip() or "interested"
                    url = str(payload.get("url", "")).strip()[:2000]
                    c.execute(
                        "INSERT INTO interests (name, description, status, url, created_at) VALUES (?, ?, ?, ?, ?)",
                        (name, description, status, url, now),
                    )
                else:  # audit_log
                    tool_name = str(payload.get("tool_name", "")).strip() or "unknown"
                    args_summary = str(payload.get("args_summary", "")).strip()[:500]
                    c.execute(
                        "INSERT INTO audit_log (tool_name, args_summary, created_at) VALUES (?, ?, ?)",
                        (tool_name, args_summary, now),
                    )
                row_id = c.lastrowid
                return f"Inserted into {table} id={row_id}."

            if operation == "select":
                limit = max(1, min(int(payload.get("limit", 20)), 100))
                if table in ("user_tasks", "agent_tasks", "reminders"):
                    # completed 未指定: 未完了を先に（かつ新しい id 優先）。明示 false は期日順、true は最近完了順。
                    if "completed" not in payload:
                        order = "ORDER BY completed ASC, id DESC"
                    elif payload.get("completed"):
                        order = "ORDER BY id DESC"
                    else:
                        order = "ORDER BY scheduled_at ASC"
                    where = []
                    params: list[Any] = []
                    if "completed" in payload:
                        where.append("completed = ?")
                        params.append(1 if payload.get("completed") else 0)
                    if table == "agent_tasks":
                        if "source" in payload:
                            raw_src = str(payload["source"]).strip().lower()
                            if raw_src in ("heartbeat", "self"):
                                where.append("source = ?")
                                params.append(raw_src)
                        if "status" in payload:
                            raw_st = str(payload["status"]).strip().lower()
                            if raw_st in ("pending", "in_progress", "completed", "cancelled"):
                                where.append("status = ?")
                                params.append(raw_st)
                    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
                    params.append(limit)
                    select_cols = (
                        "id, scheduled_at, content, completed, source, status, created_at"
                        if table == "agent_tasks"
                        else "id, scheduled_at, content, completed, created_at"
                    )
                    c.execute(
                        f"SELECT {select_cols} FROM {table}{where_sql} {order} LIMIT ?",
                        params,
                    )
                elif table == "finances":
                    c.execute(
                        "SELECT id, amount, category, memo, date, created_at FROM finances ORDER BY date DESC, id DESC LIMIT ?",
                        (limit,),
                    )
                elif table == "interests":
                    c.execute(
                        "SELECT id, name, description, status, url, created_at FROM interests ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                else:  # audit_log
                    c.execute(
                        "SELECT id, tool_name, args_summary, created_at FROM audit_log ORDER BY id DESC LIMIT ?",
                        (limit,),
                    )
                rows = c.fetchall()
                if not rows:
                    return f"Table '{table}': no rows."
                out = [_row_to_dict(c, r) for r in rows]
                full = json.dumps(out, ensure_ascii=False, indent=0)
                if len(full) <= 4000:
                    return full
                # 4000文字を超える場合は入る件数だけ表示して残りを通知
                truncated: list[dict[str, Any]] = []
                for item in out:
                    candidate = json.dumps(truncated + [item], ensure_ascii=False, indent=0)
                    if len(candidate) > 3800:
                        break
                    truncated.append(item)
                note = (
                    f"\n(注: 全{len(out)}件中{len(truncated)}件を表示。"
                    f"残り{len(out) - len(truncated)}件は limit を減らして再取得してください)"
                )
                return json.dumps(truncated, ensure_ascii=False, indent=0) + note

            if operation == "update":
                row_id = payload.get("id")
                if row_id is None:
                    return "Error: update requires id in payload."
                row_id = int(row_id)
                allowed_cols = (
                    {"completed", "scheduled_at", "content", "source", "status"} if table == "agent_tasks"
                    else {"completed", "scheduled_at", "content"} if table in ("user_tasks", "reminders")
                    else {"amount", "category", "memo", "date"} if table == "finances"
                    else {"name", "description", "status", "url"} if table == "interests"
                    else set()
                )
                if not allowed_cols:
                    return f"Error: {table} does not support update."
                sets = []
                params: list[Any] = []
                for k, v in payload.items():
                    if k == "id":
                        continue
                    if k in allowed_cols:
                        sets.append(f"{k} = ?")
                        if k == "completed" and isinstance(v, bool):
                            params.append(1 if v else 0)
                        elif k == "scheduled_at":
                            params.append(_normalize_scheduled_at(str(v)))
                        else:
                            params.append(v)
                if not sets:
                    return "Error: no updatable fields in payload."
                params.append(row_id)
                c.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", params)
                return f"Updated {table} id={row_id}."

            if operation == "delete":
                row_id = payload.get("id")
                if row_id is None:
                    return "Error: delete requires id in payload."
                row_id = int(row_id)
                c.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
                return f"Deleted {table} id={row_id}."
    except (ValueError, TypeError, sqlite3.Error) as e:
        return f"Error: {e!s}"
    
