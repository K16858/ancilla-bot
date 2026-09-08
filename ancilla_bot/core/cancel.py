"""
エージェント処理のキャンセル制御（スレッド間共有）
"""

from __future__ import annotations

import threading

_cancel_event = threading.Event()
_suspend_event = threading.Event()


def reset_cancel() -> None:
    _cancel_event.clear()


def request_cancel() -> None:
    _cancel_event.set()


def is_cancelled() -> bool:
    return _cancel_event.is_set()


def request_suspend() -> None:
    _suspend_event.set()


def clear_suspend() -> None:
    _suspend_event.clear()


def is_suspended() -> bool:
    return _suspend_event.is_set()
