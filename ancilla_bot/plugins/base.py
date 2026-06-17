"""
ドメインプラグインの基底クラス
"""

from __future__ import annotations

from abc import ABC
from typing import Any, Callable


class AncillaPlugin(ABC):
    name: str = ""
    tools: dict[str, Callable[..., str]] = {}
    descriptions: dict[str, str] = {}

    def on_session_start(self, context: dict[str, Any]) -> None:
        _ = context

    def on_session_end(self, messages: list[dict[str, str]]) -> None:
        _ = messages

    def on_ambient_signal(self, signal: dict[str, Any]) -> None:
        _ = signal
