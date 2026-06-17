"""
組み込みシグナルコレクター
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from ancilla_bot.ambient.base import AmbientSignal, SignalCollector

_WORKSPACE = Path(os.getenv("ANCILLA_WORKSPACE_DIR", "workspace"))
_FS_SNAPSHOT: dict[str, float] = {}


class TimeSignalCollector(SignalCollector):
    def collect(self) -> AmbientSignal:
        now = datetime.now()
        return {
            "type": "time",
            "value": {
                "hour": now.hour,
                "weekday": now.weekday(),
                "is_active_hours": 10 <= now.hour <= 23,
            },
            "timestamp": now.isoformat(),
        }


class ConversationGapCollector(SignalCollector):
    def __init__(self, last_user_input_time: float) -> None:
        self._last_user_input_time = last_user_input_time

    def collect(self) -> AmbientSignal | None:
        if self._last_user_input_time <= 0:
            return None
        gap = max(0.0, datetime.now().timestamp() - self._last_user_input_time)
        return {
            "type": "conversation_gap",
            "value": {"conversation_gap_seconds": int(gap)},
            "timestamp": datetime.now().isoformat(),
        }


class FilesystemCollector(SignalCollector):
    watched_dir: Path = _WORKSPACE

    def collect(self) -> AmbientSignal | None:
        global _FS_SNAPSHOT
        current: dict[str, float] = {}
        root = self.watched_dir
        if not root.exists():
            return None
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    rel = str(path.relative_to(root)).replace("\\", "/")
                    current[rel] = path.stat().st_mtime
                except OSError:
                    continue
        new_files = [p for p, mtime in current.items() if p not in _FS_SNAPSHOT]
        changed_files = [
            p
            for p, mtime in current.items()
            if p in _FS_SNAPSHOT and _FS_SNAPSHOT[p] != mtime and p not in new_files
        ]
        _FS_SNAPSHOT = current
        if not new_files and not changed_files:
            return None
        return {
            "type": "filesystem",
            "value": {
                "filesystem_new_files": new_files or None,
                "filesystem_changed_files": changed_files or None,
            },
            "timestamp": datetime.now().isoformat(),
        }


class CameraSignalCollector(SignalCollector):
    enabled: bool = False
    interval_minutes: int = int(os.getenv("ANCILLA_CAMERA_INTERVAL", "0") or "0")

    def collect(self) -> AmbientSignal | None:
        if self.interval_minutes <= 0:
            return None
        return None
