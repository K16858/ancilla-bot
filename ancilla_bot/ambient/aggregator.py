"""
環境シグナルのアグリゲーション
"""

from __future__ import annotations

from ancilla_bot.ambient.base import AmbientSignal, SignalCollector
from ancilla_bot.ambient.collectors import (
    CameraSignalCollector,
    ConversationGapCollector,
    FilesystemCollector,
    TimeSignalCollector,
)


def collect_context_snapshot(last_user_input_time: float | None = None) -> dict[str, AmbientSignal]:
    """現在の環境コンテキストを収集して返す。"""
    gap_time = last_user_input_time if last_user_input_time is not None else 0.0
    collectors: list[SignalCollector] = [
        TimeSignalCollector(),
        ConversationGapCollector(gap_time),
        FilesystemCollector(),
        CameraSignalCollector(),
    ]
    snapshot: dict[str, AmbientSignal] = {}
    for collector in collectors:
        if not collector.enabled:
            continue
        signal = collector.collect()
        if signal is not None:
            snapshot[signal["type"]] = signal
    return snapshot
