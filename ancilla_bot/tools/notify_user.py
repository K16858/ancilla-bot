"""
notify_user ツール本体
"""

from __future__ import annotations

from typing import Literal

from ancilla_bot.notifications import append_notification, append_report


def notify_user(
    message: str,
    *,
    source: Literal["system", "report", "email"] = "report",
    level: Literal["info", "notice", "warning", "critical"] = "info",
    title: str | None = None,
) -> str:
    """
    通知を 1 件送る高レベルツール。

    - source="report": 自律報告（提案箱相当）。append_report を使う。
    - source="email": メール由来の通知。append_notification(source="email") を使う。
    - source="system": Heartbeat や内部イベント由来。append_notification(source="system") を使う。

    成功時は "OK" を返し、エラーはメッセージとして返す想定。
    """
    try:
        if source == "report":
            append_report(title=title or "自律報告", message=message, detail=None)
        elif source in {"email", "system"}:
            append_notification(
                message=message,
                source=source,
                level=level,
                title=title,
                detail=None,
            )
        else:
            return f"Error: unsupported source '{source}'."
    except Exception as e:
        return f"Error: notify_user failed: {e}"
    return "OK"

