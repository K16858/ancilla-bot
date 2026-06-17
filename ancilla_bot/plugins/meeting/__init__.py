"""
Meeting Capture Plugin
"""

from __future__ import annotations

from typing import Any

from ancilla_bot.plugins.base import AncillaPlugin

_active_meeting: dict[str, Any] | None = None


def start_meeting(title: str = "", **kwargs: Any) -> str:
    global _active_meeting
    _ = kwargs
    _active_meeting = {"title": title or "Untitled", "status": "recording"}
    return f"Meeting started: {title or 'Untitled'}"


def end_meeting(**kwargs: Any) -> str:
    global _active_meeting
    _ = kwargs
    if _active_meeting is None:
        return "Error: no active meeting."
    title = _active_meeting.get("title", "Untitled")
    _active_meeting = None
    return f"Meeting ended: {title}. Summary will be stored when STT is configured."


def search_meetings(query: str, **kwargs: Any) -> str:
    _ = kwargs
    return f"No meeting records found for query: {query}"


class MeetingPlugin(AncillaPlugin):
    name = "meeting"
    tools = {
        "start_meeting": start_meeting,
        "end_meeting": end_meeting,
        "search_meetings": search_meetings,
    }
    descriptions = {
        "start_meeting": "Start meeting capture. action_input: {\"title\": \"...\"}.",
        "end_meeting": "End meeting capture and store summary. action_input: {}.",
        "search_meetings": "Search past meetings. action_input: {\"query\": \"...\"}.",
    }
