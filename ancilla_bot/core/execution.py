"""AgentExecution: interactive / autonomous / maintenance の排他と suspend/resume。"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Literal

from loguru import logger

from ancilla_bot.core.cancel import clear_suspend, request_suspend

Kind = Literal["interactive", "autonomous", "maintenance"]
State = Literal["ready", "running", "suspended", "waiting", "completed", "failed"]

PROGRESS_EVERY_TOOLS = max(1, int(os.getenv("ANCILLA_PROGRESS_TOOLS", "8")))
PROGRESS_EVERY_SEC = max(5.0, float(os.getenv("ANCILLA_PROGRESS_SEC", "45")))
FIRST_REPLY_SEC = max(5.0, float(os.getenv("ANCILLA_FIRST_REPLY_SEC", "50")))


class AgentExecution:
    def __init__(self) -> None:
        self.kind: Kind | None = None
        self.state: State = "ready"
        self.run_id: str | None = None


class AgentRuntime:
    def __init__(self) -> None:
        self._cv = threading.Condition()
        self.current = AgentExecution()
        self._resume_ids: list[str] = []
        self._resume_handler: Callable[[str], None] | None = None
        self._tool_count = 0
        self._started_at = 0.0
        self._last_progress_at = 0.0
        self._last_progress_tools = 0
        self._first_event = threading.Event()
        self._first_text: str | None = None
        self._returned_early = False

    def set_resume_handler(self, handler: Callable[[str], None] | None) -> None:
        self._resume_handler = handler

    def busy(self) -> bool:
        with self._cv:
            return self.current.state == "running"

    def current_kind(self) -> Kind | None:
        with self._cv:
            return self.current.kind if self.current.state == "running" else None

    def try_begin(self, kind: Kind) -> bool:
        with self._cv:
            if self.current.state == "running":
                return False
            self._start_locked(kind)
            return True

    def begin(self, kind: Kind) -> None:
        with self._cv:
            while self.current.state == "running":
                self._cv.wait()
            self._start_locked(kind)

    def preempt_for_interactive(self) -> None:
        with self._cv:
            while self.current.state == "running" and self.current.kind == "interactive":
                self._cv.wait(timeout=0.5)
            if self.current.state == "running":
                request_suspend()
                while self.current.state == "running":
                    self._cv.wait(timeout=0.5)
                clear_suspend()
            self._start_locked("interactive")

    def end(self, *, failed: bool = False) -> None:
        resume_id: str | None = None
        with self._cv:
            was = self.current.kind
            self.current.kind = None
            self.current.state = "failed" if failed else "ready"
            self._cv.notify_all()
            if was == "interactive" and self._resume_ids:
                resume_id = self._resume_ids.pop(0)
        if resume_id and self._resume_handler is not None:
            rid = resume_id
            threading.Thread(
                target=self._resume_handler,
                args=(rid,),
                daemon=True,
                name="agent-resume",
            ).start()

    def note_suspended(self, run_id: str) -> None:
        with self._cv:
            if run_id and run_id not in self._resume_ids:
                self._resume_ids.append(run_id)
            self.current.state = "suspended"

    def note_tool(self) -> None:
        self._tool_count += 1
        if self.current.kind != "interactive":
            return
        now = time.time()
        if (
            self._tool_count - self._last_progress_tools >= PROGRESS_EVERY_TOOLS
            or (self._started_at and now - self._last_progress_at >= PROGRESS_EVERY_SEC)
        ):
            self._last_progress_tools = self._tool_count
            self._last_progress_at = now
            elapsed = now - self._started_at if self._started_at else 0.0
            text = phrase_progress(self._tool_count, elapsed)
            first = not self._first_event.is_set()
            self.offer_first_reply(text)
            if first:
                self._returned_early = True
            else:
                from ancilla_bot.notifications import append_notification

                append_notification(text, source="system", level="info", detail="progress")

    def offer_first_reply(self, text: str) -> None:
        if self._first_event.is_set():
            return
        self._first_text = (text or "").strip() or None
        self._first_event.set()

    def wait_first_reply(self, timeout_sec: float) -> str | None:
        if self._first_event.wait(timeout=timeout_sec):
            return self._first_text
        self._returned_early = True
        elapsed = time.time() - self._started_at if self._started_at else 0.0
        text = phrase_progress(self._tool_count, elapsed)
        self.offer_first_reply(text)
        return text

    def mark_returned_early(self) -> None:
        self._returned_early = True

    def _start_locked(self, kind: Kind) -> None:
        self.current.kind = kind
        self.current.state = "running"
        self.current.run_id = None
        self._tool_count = 0
        now = time.time()
        self._started_at = now
        self._last_progress_at = now
        self._last_progress_tools = 0
        self._first_event.clear()
        self._first_text = None
        self._returned_early = False


_runtime: AgentRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> AgentRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = AgentRuntime()
        return _runtime


def phrase_progress(tool_count: int, elapsed_sec: float) -> str:
    from ancilla_bot.llm import send_chat

    try:
        raw = send_chat(
            [
                {
                    "role": "user",
                    "content": (
                        "Write one short Japanese sentence telling the user work is still in progress. "
                        f"tools={tool_count} elapsed_sec={int(elapsed_sec)}. No quotes."
                    ),
                }
            ],
            think=False,
        )
        text = (raw or "").strip().splitlines()[0].strip()
        if text:
            return text[:200]
    except Exception as e:
        logger.debug("progress phrasing failed: {}", e)
    return f"作業を継続中です（tools={tool_count}）。"
