"""ハートビート due の失敗カウント・バックオフ・poison 判定。"""

from __future__ import annotations

import time
from typing import Any

MAX_FAILS = 3
INTERVAL_SEC = 60

_fails: dict[str, int] = {}
_retry_at: dict[str, float] = {}


def due_key(row: dict[str, Any]) -> str:
    table = row.get("_table") or "reminders"
    return f"{table}:{row['id']}"


def is_permanent_failure(response: str) -> bool:
    if not response or len(response.strip()) < 5:
        return True
    stripped = response.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return True
    return response.startswith("内部エラー")


def actionable(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = time.monotonic()
    return [r for r in rows if _retry_at.get(due_key(r), 0) <= now]


def record_success(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        key = due_key(row)
        _fails.pop(key, None)
        _retry_at.pop(key, None)


def record_failure(rows: list[dict[str, Any]], response: str) -> list[dict[str, Any]]:
    """失敗を記録し、上限に達した行（poison）を返す。"""
    poison: list[dict[str, Any]] = []
    now = time.monotonic()
    permanent = is_permanent_failure(response)
    for row in rows:
        key = due_key(row)
        n = MAX_FAILS if permanent else _fails.get(key, 0) + 1
        _fails[key] = n
        if n >= MAX_FAILS:
            poison.append(row)
            _fails.pop(key, None)
            _retry_at.pop(key, None)
        else:
            _retry_at[key] = now + INTERVAL_SEC * (2 ** (n - 1))
    return poison
