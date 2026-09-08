"""
構造化ユーザーモデル。正本は memories。yaml は projection。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(os.getenv("ANCILLA_PERSONAL_MODEL_PATH", "data/personal_model.yaml"))


def _default_model() -> dict[str, Any]:
    return {
        "identity": {
            "name": "",
            "role": "",
            "timezone": "Asia/Tokyo",
            "language": "ja",
        },
        "goals": {"short_term": [], "long_term": []},
        "domains": [],
        "patterns": {
            "active_hours": "10:00-23:00",
            "communication_style": "casual_japanese",
            "preferred_response_length": "concise",
            "interruption_tolerance": "low",
        },
        "knowledge_graph": {"nodes": [], "edges": []},
    }


def load() -> dict[str, Any]:
    from ancilla_bot.heartbeat.db import list_memories
    from ancilla_bot.memory.store import memories_to_personal_model

    return memories_to_personal_model(list_memories(durable_only=True))


def get_context_slice(situation: str = "") -> dict[str, Any]:
    model = load()
    _ = situation
    return {
        "identity": model.get("identity", {}),
        "goals": model.get("goals", {}),
        "domains": model.get("domains", []),
        "patterns": model.get("patterns", {}),
    }


def update_user_goal(goal: str, term: str = "short", **kwargs: Any) -> str:
    _ = kwargs
    from ancilla_bot.heartbeat.db import manage_state

    subject = "long" if term == "long" else "short"
    return manage_state(
        "memories",
        "insert",
        {"kind": "goal", "subject": subject, "content": goal},
    )


def get_user_context(**kwargs: Any) -> str:
    _ = kwargs
    return yaml.safe_dump(get_context_slice(), allow_unicode=True, sort_keys=False)
