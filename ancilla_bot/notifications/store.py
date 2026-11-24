"""
通知のキュー保存と SQLite 配信ログ。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from loguru import logger

from ancilla_bot.heartbeat import db

DEFAULT_NOTIFICATIONS_DIR = Path(
    os.getenv("ANCILLA_NOTIFICATIONS_DIR", "data/notifications")
)
PENDING_FILE = "pending.jsonl"

_SCHEMA_NOTIFICATIONS = """
CREATE TABLE IF NOT EXISTS notification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT,
    message TEXT NOT NULL,
    detail TEXT
)
"""

_hooks_lock = threading.Lock()
_notif_hooks: list[Callable[[dict[str, Any]], None]] = []


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with closing(db._conn()) as c:
        c.row_factory = sqlite3.Row
        c.execute(_SCHEMA_NOTIFICATIONS)
        with c:
            yield c


def subscribe_notifications(cb: Callable[[dict[str, Any]], None]) -> None:
    with _hooks_lock:
        if cb not in _notif_hooks:
            _notif_hooks.append(cb)


def clear_notification_hooks() -> None:
    with _hooks_lock:
        _notif_hooks.clear()


def _emit(event: dict[str, Any]) -> None:
    with _hooks_lock:
        hooks = list(_notif_hooks)
    for cb in hooks:
        try:
            cb(event)
        except Exception as exc:
            logger.warning("notification hook failed: {}", exc)


def _dir() -> Path:
    return Path(os.getenv("ANCILLA_NOTIFICATIONS_DIR", str(DEFAULT_NOTIFICATIONS_DIR)))


def _pending_path() -> Path:
    return _dir() / PENDING_FILE


def append_notification(
    message: str,
    source: str = "system",
    level: str = "info",
    detail: str | None = None,
    title: str | None = None,
    category: str | None = None,
) -> int:
    """
    送信待ちの能動通知を 1 件、pending.jsonl と SQLite の notification_events に記録する。

    source は system / report / email などを想定する。
    """
    path = _pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    ts = now.strftime("%Y-%m-%d %H:%M")
    record = {
        "ts": ts,
        "source": source,
        "level": level,
        "message": message,
    }
    if title is not None:
        record["title"] = title
    if detail is not None:
        record["detail"] = detail
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    cat = (category or "").strip() or ("report" if source == "report" else "system")
    created_at = now.isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO notification_events (created_at, source, category, level, title, message, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (created_at, source, cat, level, title, message, detail),
        )
        eid = int(cur.lastrowid)

    event = {
        "id": eid,
        "created_at": created_at,
        "source": source,
        "category": cat,
        "level": level,
        "title": title,
        "message": message,
        "detail": detail,
    }
    _emit(event)
    return eid


def append_report(title: str, message: str, detail: str | None = None) -> int:
    """
    自律的な報告・共有（提案箱相当）をキューに追加するヘルパー
    """
    return append_notification(
        message=message,
        source="report",
        level="info",
        detail=detail,
        title=title,
        category="report",
    )


def list_notifications(*, since_id: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    """since_id > 0 なら以降のイベントを昇順、0 以下なら最新 limit 件を降順で返す。"""
    lim = max(1, min(int(limit), 200))
    since = int(since_id or 0)
    with _conn() as c:
        if since > 0:
            rows = c.execute(
                "SELECT * FROM notification_events WHERE id > ? ORDER BY id ASC LIMIT ?",
                (since, lim),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM notification_events ORDER BY id DESC LIMIT ?",
                (lim,),
            ).fetchall()
    return [dict(r) for r in rows]


def notifications_after(since_id: int, limit: int = 50) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 200))
    since = max(0, int(since_id or 0))
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM notification_events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (since, lim),
        ).fetchall()
    return [dict(r) for r in rows]


def last_notification_id() -> int:
    with _conn() as c:
        row = c.execute("SELECT COALESCE(MAX(id), 0) AS m FROM notification_events").fetchone()
    return int(row["m"]) if row else 0
