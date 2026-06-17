"""
Native tool calling 用 JSON Schema（Ollama tools parameters）
"""

from __future__ import annotations

from typing import Any

NATIVE_EXCLUDED_TOOLS: frozenset[str] = frozenset({"manage_state"})

_EMPTY_OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def _schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        out["required"] = required
    return out


TOOL_PARAMETERS: dict[str, dict[str, Any]] = {
    "get_time": _EMPTY_OBJECT,
    "web_search": _schema(
        {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {"type": "integer", "description": "Max results (default 5)"},
        },
        required=["query"],
    ),
    "fetch_page": _schema(
        {
            "url": {"type": "string", "description": "HTTP or HTTPS URL"},
            "max_chars": {"type": "integer", "description": "Max characters to return"},
        },
        required=["url"],
    ),
    "list_workspace": _schema(
        {
            "path": {"type": "string", "description": "Relative path inside workspace"},
            "max_entries": {"type": "integer", "description": "Max entries (default 100)"},
            "max_depth": {"type": "integer", "description": "Max directory depth (default 4)"},
        },
    ),
    "read_file": _schema(
        {
            "path": {"type": "string", "description": "File path relative to workspace"},
            "max_lines": {"type": "integer", "description": "Max lines to read"},
        },
        required=["path"],
    ),
    "write_file": _schema(
        {
            "path": {"type": "string", "description": "File path relative to workspace"},
            "content": {"type": "string", "description": "Full file content"},
        },
        required=["path", "content"],
    ),
    "edit_file_safe": _schema(
        {
            "path": {"type": "string", "description": "File path relative to workspace"},
            "operation": {
                "type": "string",
                "enum": ["append", "replace"],
                "description": "append or replace",
            },
            "content": {"type": "string", "description": "Content for append"},
            "old": {"type": "string", "description": "String to replace (replace mode)"},
            "new": {"type": "string", "description": "Replacement text"},
            "start_line": {"type": "integer", "description": "Start line for line replace (1-based)"},
            "end_line": {"type": "integer", "description": "End line for line replace (1-based)"},
        },
        required=["path", "operation"],
    ),
    "bash": _schema(
        {
            "command": {"type": "string", "description": "Shell command to run"},
            "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 60)"},
            "stdin_text": {"type": "string", "description": "Optional stdin input"},
        },
        required=["command"],
    ),
    "search_memory": _schema(
        {
            "query": {"type": "string", "description": "Search query for past summaries"},
            "max_results": {"type": "integer", "description": "Max results (default 3)"},
        },
        required=["query"],
    ),
    "add_task": _schema(
        {
            "content": {"type": "string", "description": "Task description"},
            "scheduled_at": {
                "type": "string",
                "description": "YYYY-MM-DD HH:MM:SS (optional, defaults to now)",
            },
        },
        required=["content"],
    ),
    "list_tasks": _schema(
        {
            "completed": {"type": "boolean", "description": "Filter by completion (default false)"},
            "limit": {"type": "integer", "description": "Max tasks to return (default 10)"},
        },
    ),
    "complete_task": _schema(
        {"id": {"type": "integer", "description": "Task id to mark complete"}},
        required=["id"],
    ),
    "add_reminder": _schema(
        {
            "content": {"type": "string", "description": "Reminder text"},
            "scheduled_at": {"type": "string", "description": "YYYY-MM-DD HH:MM:SS"},
        },
        required=["content", "scheduled_at"],
    ),
    "add_finance": _schema(
        {
            "amount": {"type": "number", "description": "Amount (negative for expense)"},
            "category": {"type": "string", "description": "Category name"},
            "memo": {"type": "string", "description": "Optional memo"},
            "date": {"type": "string", "description": "YYYY-MM-DD (optional)"},
        },
        required=["amount", "category"],
    ),
    "add_interest": _schema(
        {
            "name": {"type": "string", "description": "Topic name"},
            "description": {"type": "string", "description": "Optional description"},
            "url": {"type": "string", "description": "Optional reference URL"},
        },
        required=["name"],
    ),
    "get_user_context": _EMPTY_OBJECT,
    "update_user_goal": _schema(
        {
            "goal": {"type": "string", "description": "Goal text"},
            "term": {
                "type": "string",
                "enum": ["short", "long"],
                "description": "Goal term (default short)",
            },
        },
        required=["goal"],
    ),
    "notify_user": _schema(
        {
            "message": {"type": "string", "description": "Notification body"},
            "title": {"type": "string", "description": "Optional title"},
            "source": {
                "type": "string",
                "enum": ["report", "system", "email"],
                "description": "Notification source",
            },
            "level": {
                "type": "string",
                "enum": ["info", "notice", "warning", "critical"],
                "description": "Severity level",
            },
        },
        required=["message"],
    ),
    "use_edgedevice": _schema(
        {
            "target": {"type": "string", "description": "Optional edge device target"},
            "reason": {"type": "string", "description": "Why edge session is needed"},
        },
    ),
    "end_edge_session": _EMPTY_OBJECT,
    "get_image": _schema(
        {
            "reason": {"type": "string", "description": "Why capture is needed"},
            "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 60)"},
        },
    ),
    "get_audio": _schema(
        {
            "reason": {"type": "string", "description": "Why capture is needed"},
            "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 60)"},
        },
    ),
    # Plugin tools (when ANCILLA_PLUGINS enables them)
    "search_arxiv": _schema(
        {
            "query": {"type": "string", "description": "arXiv search query"},
            "max_results": {"type": "integer", "description": "Max papers (default 5)"},
        },
        required=["query"],
    ),
    "add_learning_item": _schema(
        {
            "concept": {"type": "string", "description": "Concept to learn"},
            "domain": {"type": "string", "description": "Subject domain"},
            "notes": {"type": "string", "description": "Optional notes"},
        },
        required=["concept", "domain"],
    ),
    "review_due": _EMPTY_OBJECT,
    "record_review": _schema(
        {
            "item_id": {"type": "integer", "description": "Learning item id"},
            "quality": {"type": "integer", "description": "Review quality score"},
        },
        required=["item_id", "quality"],
    ),
    "start_meeting": _schema(
        {"title": {"type": "string", "description": "Meeting title"}},
    ),
    "end_meeting": _EMPTY_OBJECT,
    "search_meetings": _schema(
        {"query": {"type": "string", "description": "Search query"}},
        required=["query"],
    ),
}


def get_native_parameters(tool_name: str) -> dict[str, Any]:
    return TOOL_PARAMETERS.get(tool_name, _EMPTY_OBJECT)
