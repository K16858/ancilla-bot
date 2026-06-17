"""
Learning Companion Plugin
"""

from __future__ import annotations

from typing import Any

from ancilla_bot.plugins.base import AncillaPlugin


def add_learning_item(concept: str, domain: str, notes: str = "", **kwargs: Any) -> str:
    _ = kwargs
    return f"Learning item registered: {concept} ({domain}). notes={notes}"


def review_due(**kwargs: Any) -> str:
    _ = kwargs
    return "No review items due today."


def record_review(item_id: int, quality: int, **kwargs: Any) -> str:
    _ = kwargs
    return f"Review recorded for item {item_id} with quality {quality}."


class LearningPlugin(AncillaPlugin):
    name = "learning"
    tools = {
        "add_learning_item": add_learning_item,
        "review_due": review_due,
        "record_review": record_review,
    }
    descriptions = {
        "add_learning_item": (
            "Register a learning item. action_input: {\"concept\": \"...\", \"domain\": \"...\", \"notes\": \"...\"}."
        ),
        "review_due": "List items due for review today. action_input: {}.",
        "record_review": (
            "Record a review result. action_input: {\"item_id\": 1, \"quality\": 4}."
        ),
    }

    def on_session_start(self, context: dict[str, Any]) -> None:
        due = review_due()
        if due and "No review" not in due:
            context["learning_notice"] = due
