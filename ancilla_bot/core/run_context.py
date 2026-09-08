"""実行の出所。ツールはシグネチャを変えずここから読む。"""

from __future__ import annotations

from contextvars import ContextVar

run_source: ContextVar[str] = ContextVar("run_source", default="unknown")

_AUTONOMOUS = frozenset({"idle_reflection", "heartbeat", "proactive"})


def is_autonomous() -> bool:
    return run_source.get() in _AUTONOMOUS


def current_source() -> str:
    src = run_source.get()
    if src in ("idle_reflection", "proactive"):
        return "idle"
    if src == "heartbeat":
        return "scheduler"
    return "user"
