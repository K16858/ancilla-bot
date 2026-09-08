"""
notify_user ツール本体
"""

from __future__ import annotations

from typing import Literal

from ancilla_bot.heartbeat.db import try_record_notification_send, user_commitment_exists
from ancilla_bot.notifications import append_notification, append_report

_INTENTS = frozenset({"inform", "suggest", "remind", "request_action", "warning"})
_ACTION_INTENTS = frozenset({"remind", "request_action"})


def notify_user(
    message: str,
    *,
    intent: str,
    source: Literal["system", "report", "email"] = "report",
    level: Literal["info", "notice", "warning", "critical"] = "info",
    title: str | None = None,
    commitment_id: int | None = None,
    subject: str | None = None,
    **kwargs: object,
) -> str:
    """
    通知を 1 件送る。intent は必須。remind / request_action は user-owned commitment_id が必要。
    """
    _ = kwargs
    intent_n = str(intent or "").strip().lower()
    if intent_n not in _INTENTS:
        return "Error: intent must be inform, suggest, remind, request_action, or warning."
    if intent_n in _ACTION_INTENTS:
        if commitment_id is None:
            return "Error: remind/request_action requires commitment_id of a user-owned reminder or user_task."
        try:
            cid = int(commitment_id)
        except (TypeError, ValueError):
            return "Error: commitment_id must be an integer."
        if not user_commitment_exists(cid):
            return "Error: commitment_id is not a user-owned reminder or user_task."
        subject_key = f"commitment:{cid}"
    else:
        subject_key = (subject or "").strip()
        cid = None

    if subject_key and not try_record_notification_send(intent_n, subject_key):
        return "Error: already notified for this intent and subject."

    try:
        detail = f"intent={intent_n}"
        if cid is not None:
            detail += f" commitment_id={cid}"
        if source == "report":
            append_report(title=title or "自律報告", message=message, detail=detail)
        elif source in {"email", "system"}:
            append_notification(
                message=message,
                source=source,
                level=level,
                title=title,
                detail=detail,
            )
        else:
            return f"Error: unsupported source '{source}'."
    except Exception as e:
        return f"Error: notify_user failed: {e}"
    return "OK"
