"""長期記憶の正本は ancilla.db の memories。USER.md と personal_model.yaml は projection。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ancilla_bot.personal_model import DEFAULT_PATH as PERSONAL_MODEL_PATH
from ancilla_bot.personal_model import _default_model
from ancilla_bot.tools.workspace_io import get_workspace_root

_USER_MD_HEADER = "# ユーザーについて\n"


def _user_md_path() -> Path:
    return get_workspace_root() / "USER.md"


def memories_to_user_md(rows: list[dict[str, Any]]) -> str:
    sections: dict[str, list[str]] = {"profile": [], "fact": [], "goal": [], "note": []}
    for row in rows:
        kind = str(row.get("kind") or "note")
        if kind not in sections:
            kind = "note"
        subject = str(row.get("subject") or "").strip()
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        line = f"- {subject}: {content}" if subject else f"- {content}"
        sections[kind].append(line)
    parts = [_USER_MD_HEADER.rstrip()]
    titles = {"profile": "プロフィール", "fact": "事実", "goal": "目標", "note": "メモ"}
    for kind in ("profile", "fact", "goal", "note"):
        lines = sections[kind]
        if not lines:
            continue
        parts.append(f"\n## {titles[kind]}\n")
        parts.extend(lines)
    return "\n".join(parts).rstrip() + "\n"


def memories_to_personal_model(rows: list[dict[str, Any]]) -> dict[str, Any]:
    model = _default_model()
    for row in rows:
        kind = str(row.get("kind") or "")
        subject = str(row.get("subject") or "").strip()
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        if kind == "profile":
            identity = model.setdefault("identity", {})
            key = subject if subject in ("name", "role", "timezone", "language") else ""
            if key:
                identity[key] = content
            elif subject:
                model.setdefault("domains", []).append({"name": subject, "notes": content})
            else:
                identity["role"] = content
        elif kind == "goal":
            term = "long_term" if subject == "long" else "short_term"
            model.setdefault("goals", {}).setdefault(term, []).append(
                {"goal": content, "status": "active"}
            )
    return model


def project_memories() -> None:
    from ancilla_bot.heartbeat.db import list_memories

    rows = list_memories(durable_only=True)
    user_path = _user_md_path()
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(memories_to_user_md(rows), encoding="utf-8")
    model = memories_to_personal_model(rows)
    PERSONAL_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PERSONAL_MODEL_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(model, f, allow_unicode=True, sort_keys=False)


def maybe_import_user_md() -> None:
    from ancilla_bot.heartbeat.db import list_memories, manage_state

    if list_memories():
        return
    path = _user_md_path()
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8").strip()
    if not text or text == _USER_MD_HEADER.strip():
        return
    manage_state(
        "memories",
        "insert",
        {"kind": "profile", "subject": "imported", "content": text},
    )
