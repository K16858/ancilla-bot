"""
通知のキュー保存
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

DEFAULT_NOTIFICATIONS_DIR = Path(
    os.getenv("ANCILLA_NOTIFICATIONS_DIR", "data/notifications")
)
PENDING_FILE = "pending.jsonl"


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
) -> None:
    """
    送信待ちの能動通知を 1 件、pending.jsonl に追記する。

    source は system / report / email などを想定する。
    """
    path = _pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
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


def append_report(title: str, message: str, detail: str | None = None) -> None:
    """
    自律的な報告・共有（提案箱相当）をキューに追加するヘルパー
    """
    append_notification(message=message, source="report", level="info", detail=detail, title=title)
