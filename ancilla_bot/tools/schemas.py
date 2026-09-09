"""
Native tool calling 用 JSON Schema（Ollama tools parameters）
"""

from __future__ import annotations

from typing import Any

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
            "unknown": {"type": "string", "description": "What to look up (sent to the search API)"},
            "hypothesis": {
                "type": "string",
                "description": "Optional guess; not included in the search query",
            },
            "max_results": {"type": "integer", "description": "Max results (default 5)"},
        },
        required=["unknown"],
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
    "trash_file": _schema(
        {"path": {"type": "string", "description": "Path to move into .trash/"}},
        required=["path"],
    ),
    "move_file": _schema(
        {
            "src": {"type": "string", "description": "Source path inside workspace"},
            "dest": {"type": "string", "description": "Destination path inside workspace"},
        },
        required=["src", "dest"],
    ),
    "workspace_inventory": _schema(
        {
            "path": {"type": "string", "description": "Relative path inside workspace"},
            "max_entries": {"type": "integer", "description": "Max entries (default 200)"},
        },
    ),
    "bash": _schema(
        {
            "command": {"type": "string", "description": "Shell command to run"},
            "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 60)"},
            "stdin_text": {"type": "string", "description": "Optional stdin input"},
        },
        required=["command"],
    ),
    "load_skill": _schema(
        {"name": {"type": "string", "description": "Skill name from the catalog"}},
        required=["name"],
    ),
    "set_mode": _schema(
        {"name": {"type": "string", "description": "Mode name (general, research, coding)"}},
        required=["name"],
    ),
    "search_memory": _schema(
        {
            "query": {"type": "string", "description": "Search query for past summaries"},
            "max_results": {"type": "integer", "description": "Max results (default 3)"},
        },
        required=["query"],
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
    "manage_state": _schema(
        {
            "table": {
                "type": "string",
                "enum": [
                    "user_tasks",
                    "agent_tasks",
                    "reminders",
                    "finances",
                    "interests",
                    "audit_log",
                    "idle_memory",
                    "memories",
                ],
                "description": "Target table",
            },
            "operation": {
                "type": "string",
                "enum": ["insert", "select", "update", "delete"],
                "description": "CRUD operation",
            },
            "payload": {
                "type": "object",
                "description": "Operation args (id, content, scheduled_at, completed, limit, ...)",
                "properties": {
                    "id": {"type": "integer"},
                    "content": {"type": "string"},
                    "scheduled_at": {"type": "string"},
                    "completed": {"type": "boolean"},
                    "limit": {"type": "integer"},
                    "source": {"type": "string"},
                    "status": {"type": "string"},
                    "owner": {"type": "string"},
                    "kind": {"type": "string"},
                    "subject": {"type": "string"},
                    "amount": {"type": "number"},
                    "category": {"type": "string"},
                    "memo": {"type": "string"},
                    "date": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        required=["table", "operation"],
    ),
    "notify_user": _schema(
        {
            "message": {"type": "string", "description": "Notification body"},
            "intent": {
                "type": "string",
                "enum": ["inform", "suggest", "remind", "request_action", "warning"],
                "description": "Why this notification is sent",
            },
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
            "commitment_id": {
                "type": "integer",
                "description": "user-owned reminder or user_task id (required for remind/request_action)",
            },
            "subject": {
                "type": "string",
                "description": "Dedupe key for inform/suggest/warning",
            },
        },
        required=["message", "intent"],
    ),
    "finish": _schema(
        {"message": {"type": "string", "description": "User-facing reply"}},
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
    "search_arxiv": _schema(
        {
            "query": {"type": "string", "description": "arXiv search query"},
            "max_results": {"type": "integer", "description": "Max papers (default 5)"},
        },
        required=["query"],
    ),
}


def get_native_parameters(tool_name: str) -> dict[str, Any]:
    from ancilla_bot.mcp.bridge import MCP_NATIVE_SCHEMAS

    if tool_name in MCP_NATIVE_SCHEMAS:
        return MCP_NATIVE_SCHEMAS[tool_name]
    return TOOL_PARAMETERS.get(tool_name, _EMPTY_OBJECT)
