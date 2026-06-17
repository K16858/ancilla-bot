"""
プラグインのロードとツール登録
"""

from __future__ import annotations

import os
from typing import Any, Callable

from ancilla_bot.plugins.research import ResearchPlugin
from ancilla_bot.plugins.learning import LearningPlugin
from ancilla_bot.plugins.meeting import MeetingPlugin

_PLUGIN_TYPES = {
    "research": ResearchPlugin,
    "learning": LearningPlugin,
    "meeting": MeetingPlugin,
}


def load_plugins() -> list[Any]:
    raw = os.getenv("ANCILLA_PLUGINS", "").strip()
    if not raw:
        return []
    plugins = []
    for name in raw.split(","):
        key = name.strip().lower()
        cls = _PLUGIN_TYPES.get(key)
        if cls is not None:
            plugins.append(cls())
    return plugins


def register_plugin_tools(
    registry: dict[str, Callable[..., str]],
    descriptions: dict[str, str],
) -> list[Any]:
    plugins = load_plugins()
    for plugin in plugins:
        registry.update(plugin.tools)
        descriptions.update(plugin.descriptions)
    return plugins
