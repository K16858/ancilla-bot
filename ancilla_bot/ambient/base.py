"""
環境シグナルの抽象化
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class AmbientSignal(TypedDict):
    type: str
    value: Any
    timestamp: str


class SignalCollector(ABC):
    enabled: bool = True

    @abstractmethod
    def collect(self) -> AmbientSignal | None: ...
