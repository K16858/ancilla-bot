from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PERSONAS_DIR = Path(os.getenv("ANCILLA_PERSONAS_DIR", "personas"))
# ponytail: process override for one task run; file is the durable primary.
_temporary_persona: str | None = None
_ALWAYS_ALLOW = frozenset({"set_persona", "load_skill", "finish"})


@dataclass(frozen=True)
class PersonaSpec:
    name: str
    role: str = ""
    goals: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    memory_read: tuple[str, ...] = ("user_model", "episodic")
    memory_write: tuple[str, ...] = ("user_model", "episodic")
    tools_deny: tuple[str, ...] = ()
    tools_require_approval: tuple[str, ...] = ()
    resources_notes: str = ""
    output: str = ""


_USER_MODEL_KINDS = frozenset({"profile", "fact", "goal"})
_EPISODIC_KINDS = frozenset({"note"})


def _personas_dir() -> Path:
    return Path(os.getenv("ANCILLA_PERSONAS_DIR", str(DEFAULT_PERSONAS_DIR)))


def active_persona_path() -> Path:
    raw = (os.getenv("ANCILLA_ACTIVE_PERSONA_PATH") or "").strip()
    if raw:
        return Path(raw)
    from ancilla_bot.cli.paths import get_root

    return get_root() / "data" / "active_persona.txt"


def _read_stored_name() -> str:
    path = active_persona_path()
    if not path.is_file():
        return "general"
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "general"
    if not key or key not in list_persona_names():
        return "general"
    return key


def _write_stored_name(name: str) -> None:
    path = active_persona_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name + "\n", encoding="utf-8")


def _from_data(name: str, data: dict[str, Any]) -> PersonaSpec:
    goals = data.get("goals")
    skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    preferred = skills.get("preferred") if isinstance(skills, dict) else []
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    read = memory.get("read") if isinstance(memory, dict) else None
    write = memory.get("write") if isinstance(memory, dict) else None
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    deny = tools.get("deny") if isinstance(tools, dict) else []
    require = tools.get("require_approval") if isinstance(tools, dict) else []
    resources = data.get("resources") if isinstance(data.get("resources"), dict) else {}
    notes = str(resources.get("notes") or "").strip() if isinstance(resources, dict) else ""
    return PersonaSpec(
        name=str(data.get("name") or name),
        role=str(data.get("role") or "").strip(),
        goals=tuple(str(x) for x in goals) if isinstance(goals, list) else (),
        preferred_skills=tuple(str(x) for x in preferred) if isinstance(preferred, list) else (),
        memory_read=tuple(str(x) for x in read)
        if isinstance(read, list)
        else ("user_model", "episodic"),
        memory_write=tuple(str(x) for x in write)
        if isinstance(write, list)
        else ("user_model", "episodic"),
        tools_deny=tuple(str(x) for x in deny) if isinstance(deny, list) else (),
        tools_require_approval=tuple(str(x) for x in require) if isinstance(require, list) else (),
        resources_notes=notes,
        output=str(data.get("output") or "").strip(),
    )


def list_persona_names() -> list[str]:
    root = _personas_dir()
    if not root.is_dir():
        return ["general"]
    names = sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "persona.yaml").is_file()
    )
    return names or ["general"]


def load_persona(name: str) -> PersonaSpec:
    key = (name or "general").strip() or "general"
    path = _personas_dir() / key / "persona.yaml"
    if not path.is_file():
        path = _personas_dir() / "general" / "persona.yaml"
    if not path.is_file():
        return PersonaSpec(name="general")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return PersonaSpec(name="general")
    if not isinstance(data, dict):
        return PersonaSpec(name="general")
    return _from_data(key, data)


def get_active_name() -> str:
    if _temporary_persona is not None:
        return _temporary_persona
    return _read_stored_name()


def get_active_persona() -> PersonaSpec:
    return load_persona(get_active_name())


def format_persona_overlay() -> str:
    spec = get_active_persona()
    lines = [f"## Active persona: {spec.name}"]
    if spec.role:
        lines.append(f"- role: {spec.role}")
    if spec.goals:
        lines.append("- goals:")
        lines.extend(f"  - {g}" for g in spec.goals)
    if spec.preferred_skills:
        lines.append("- preferred_skills: " + ", ".join(spec.preferred_skills))
    if spec.output:
        lines.append(f"- output: {spec.output}")
    return "\n".join(lines)


def set_persona(name: str, **kwargs: object) -> str:
    global _temporary_persona
    _ = kwargs
    key = (name or "").strip()
    if not key:
        return "Error: name is required."
    names = list_persona_names()
    if key not in names:
        return f"Error: unknown persona: {key}. Available: {', '.join(names)}"
    _temporary_persona = None
    try:
        _write_stored_name(key)
    except OSError as e:
        return f"Error: could not persist persona: {e}"
    return f"Persona set to {key}."


def begin_temporary_persona(name: str) -> str:
    """Switch persona for one task run without rewriting the durable primary."""
    global _temporary_persona
    key = (name or "").strip()
    if not key or key not in list_persona_names():
        return get_active_name()
    prev = get_active_name()
    _temporary_persona = key
    return prev


def end_temporary_persona() -> None:
    global _temporary_persona
    _temporary_persona = None


def tool_denied_by_persona(tool_name: str) -> bool:
    if tool_name in _ALWAYS_ALLOW:
        return False
    return tool_name in get_active_persona().tools_deny


def tool_requires_approval_by_persona(tool_name: str) -> bool:
    if tool_name in _ALWAYS_ALLOW:
        return False
    return tool_name in get_active_persona().tools_require_approval


def memory_kind_allowed(kind: str) -> bool:
    key = (kind or "").strip().lower()
    scopes = get_active_persona().memory_write
    if key in _USER_MODEL_KINDS:
        return "user_model" in scopes
    if key in _EPISODIC_KINDS:
        return "episodic" in scopes
    return False


_ROUTE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("researcher", ("論文", "arxiv", "調査", "research", "cite")),
    ("developer", ("実装", "pr", "bug", "refactor", "テスト", "code")),
    ("operator", ("docker", "ssh", "再起動", "deploy", "サーバ")),
)


def maybe_route_persona(user_input: str) -> str | None:
    """If primary is general, switch once by keyword. Returns new name or None."""
    if get_active_name() != "general":
        return None
    text = (user_input or "").casefold()
    for name, keys in _ROUTE_KEYWORDS:
        if any(k.casefold() in text for k in keys):
            msg = set_persona(name)
            if msg.startswith("Error:"):
                return None
            return name
    return None
