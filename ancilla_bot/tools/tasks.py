"""
タスク・リマインダー・家計・関心分野の専用ツール（manage_state の薄いラッパー）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ancilla_bot.heartbeat.db import manage_state


def add_task(content: str, scheduled_at: str | None = None, **kwargs: Any) -> str:
    """user_tasks にタスクを追加する。"""
    _ = kwargs
    when = scheduled_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return manage_state(
        "user_tasks",
        "insert",
        {"scheduled_at": when, "content": content},
    )


def list_tasks(completed: bool = False, limit: int = 10, **kwargs: Any) -> str:
    """user_tasks を一覧する。"""
    _ = kwargs
    return manage_state(
        "user_tasks",
        "select",
        {"completed": completed, "limit": limit},
    )


def complete_task(id: int, **kwargs: Any) -> str:
    """user_tasks のタスクを完了にする。"""
    _ = kwargs
    return manage_state("user_tasks", "update", {"id": id, "completed": 1})


def add_reminder(content: str, scheduled_at: str, **kwargs: Any) -> str:
    """reminders にリマインダーを追加する。"""
    _ = kwargs
    return manage_state(
        "reminders",
        "insert",
        {"scheduled_at": scheduled_at, "content": content},
    )


def add_finance(
    amount: float,
    category: str,
    memo: str = "",
    date: str | None = None,
    **kwargs: Any,
) -> str:
    """finances に収支を記録する。"""
    _ = kwargs
    payload: dict[str, Any] = {"amount": amount, "category": category, "memo": memo}
    if date:
        payload["date"] = date
    return manage_state("finances", "insert", payload)


def add_interest(
    name: str,
    description: str = "",
    url: str | None = None,
    **kwargs: Any,
) -> str:
    """interests に関心分野を追加する。"""
    _ = kwargs
    payload: dict[str, Any] = {"name": name, "description": description}
    if url:
        payload["url"] = url
    return manage_state("interests", "insert", payload)
