"""
Proactive 介入のスロットル制御
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from ancilla_bot.proactive.engine import ProactiveAction

MAX_PROACTIVE_PER_HOUR = int(os.getenv("ANCILLA_PROACTIVE_MAX_PER_HOUR", "2"))

_last_proactive_dt: datetime | None = None
_proactive_count_hour: int = 0
_proactive_hour_key: str = ""


def can_interrupt(action: ProactiveAction, last_proactive_dt: datetime | None) -> bool:
    """cooldown と時間あたり上限を考慮して介入可否を判断する。"""
    global _last_proactive_dt, _proactive_count_hour, _proactive_hour_key
    if MAX_PROACTIVE_PER_HOUR <= 0:
        return False

    now = datetime.now()
    hour_key = now.strftime("%Y-%m-%d-%H")
    if hour_key != _proactive_hour_key:
        _proactive_hour_key = hour_key
        _proactive_count_hour = 0

    if _proactive_count_hour >= MAX_PROACTIVE_PER_HOUR:
        return False

    ref = last_proactive_dt or _last_proactive_dt
    if ref and now - ref < timedelta(minutes=30):
        return False

    _ = action
    _last_proactive_dt = now
    _proactive_count_hour += 1
    return True
