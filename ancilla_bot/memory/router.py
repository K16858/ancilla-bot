from __future__ import annotations

from dataclasses import dataclass

from ancilla_bot.heartbeat.db import (
    get_open_working_memory,
    search_artifacts,
    search_memories,
    search_procedures,
)
from ancilla_bot.runtime.persona import memory_class_allowed

_SEMANTIC_N = 3
_PROCEDURE_N = 2
_ARTIFACT_N = 2


@dataclass(frozen=True)
class MemoryContext:
    user_id: str = "default"
    project_id: str = ""
    workspace_id: str = ""
    task_id: str = ""


def _scopes(context: MemoryContext) -> list[tuple[str, str]]:
    scopes: list[tuple[str, str]] = []
    if context.task_id.strip():
        scopes.append(("task", context.task_id.strip()))
    if context.project_id.strip():
        scopes.append(("project", context.project_id.strip()))
    if context.workspace_id.strip():
        scopes.append(("workspace", context.workspace_id.strip()))
    if context.user_id.strip():
        scopes.append(("user", context.user_id.strip()))
    scopes.append(("global", "global"))
    return scopes


def _collect(search, query: str, context: MemoryContext, limit: int) -> list[dict]:
    found: list[dict] = []
    for scope_type, scope_id in _scopes(context):
        need = limit - len(found)
        if need <= 0:
            break
        found.extend(
            search(query, scope_type=scope_type, scope_id=scope_id, n_results=need)
        )
    return found[:limit]


def _hit_line(hit: dict) -> str:
    meta = hit.get("metadata") or {}
    name = str(meta.get("name") or meta.get("subject") or "").strip()
    doc = str(hit.get("document") or "").strip()
    scope = f"{meta.get('scope_type')}/{meta.get('scope_id')}"
    body = f"{name}: {doc}" if name and doc else (name or doc)
    return f"- {body} ({scope})"


def _working_block(row: dict) -> str:
    lines = ["### Working"]
    for key in ("goal", "state", "next_actions", "resources"):
        value = str(row.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def retrieve_context(query: str, context: MemoryContext) -> str:
    sections: list[str] = []
    if context.task_id.strip() and memory_class_allowed("working", write=False):
        row = get_open_working_memory(context.task_id)
        if row:
            sections.append(_working_block(row))
    if memory_class_allowed("semantic", write=False):
        hits = _collect(search_memories, query, context, _SEMANTIC_N)
        if hits:
            sections.append("### Semantic\n" + "\n".join(_hit_line(h) for h in hits))
    if memory_class_allowed("procedural", write=False):
        hits = _collect(search_procedures, query, context, _PROCEDURE_N)
        if hits:
            sections.append("### Procedures\n" + "\n".join(_hit_line(h) for h in hits))
    if memory_class_allowed("artifact", write=False):
        hits = _collect(search_artifacts, query, context, _ARTIFACT_N)
        if hits:
            sections.append("### Artifacts\n" + "\n".join(_hit_line(h) for h in hits))
    if not sections:
        return ""
    return "## Relevant Memory\n\n" + "\n\n".join(sections)
