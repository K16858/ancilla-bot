"""
SQLite: tasks / reminders テーブル。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_CONVERSATION_DIR = Path(
    os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation")
)


def get_db_path() -> Path:
    """Heartbeat 用 DB ファイルのパス。ANCILLA_CONVERSATION_DIR 配下の ancilla.db。"""
    return DEFAULT_CONVERSATION_DIR / "ancilla.db"


def _conn() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


_SCHEMA_TASKS = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_at TEXT NOT NULL,
    content TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

_SCHEMA_REMINDERS = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scheduled_at TEXT NOT NULL,
    content TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


def ensure_schema() -> None:
    """tasks / reminders テーブルがなければ作成する。"""
    with _conn() as c:
        c.executescript(_SCHEMA_TASKS)
        c.executescript(_SCHEMA_REMINDERS)


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    names = [d[0] for d in cursor.description]
    return dict(zip(names, row))


def get_due_tasks(*, at: datetime | None = None) -> list[dict[str, Any]]:
    """
    実行予定時刻 <= at かつ未完了の tasks を返す。
    at 省略時は現在時刻。0 件なら LLM に触れず return する用途。
    """
    at = at or datetime.now()
    ts = at.strftime("%Y-%m-%d %H:%M:%S")
    ensure_schema()
    with _conn() as c:
        c.execute(
            "SELECT id, scheduled_at, content, completed, created_at FROM tasks "
            "WHERE scheduled_at <= ? AND completed = 0 ORDER BY scheduled_at ASC",
            (ts,),
        )
        rows = c.fetchall()
        return [_row_to_dict(c, r) for r in rows]


def get_due_reminders(*, at: datetime | None = None) -> list[dict[str, Any]]:
    """
    実行予定時刻 <= at かつ未完了の reminders を返す。
    at 省略時は現在時刻。
    """
    at = at or datetime.now()
    ts = at.strftime("%Y-%m-%d %H:%M:%S")
    ensure_schema()
    with _conn() as c:
        c.execute(
            "SELECT id, scheduled_at, content, completed, created_at FROM reminders "
            "WHERE scheduled_at <= ? AND completed = 0 ORDER BY scheduled_at ASC",
            (ts,),
        )
        rows = c.fetchall()
        return [_row_to_dict(c, r) for r in rows]


def has_due_work(*, at: datetime | None = None) -> bool:
    """いま実行すべきタスクまたはリマインダーが 1 件以上あるか。"""
    tasks = get_due_tasks(at=at)
    reminders = get_due_reminders(at=at)
    return len(tasks) > 0 or len(reminders) > 0
