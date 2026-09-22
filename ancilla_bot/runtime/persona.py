from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PERSONAS_DIR = Path(os.getenv("ANCILLA_PERSONAS_DIR", "personas"))
# ponytail: one persona for the process. Per-conversation if overlapping runs must differ.
_persona_name = "general"
_ALWAYS_ALLOW = frozenset({"set_persona", "load_skill", "finish"})


@dataclass(frozen=True)
class PersonaSpec:
    name: str
    role: str = ""
    goals: tuple[str, ...] = ()
    preferred_skills: tuple[str, ...] = ()
    memory_read: tuple[str, ...] = ("user_model", "episodic")
    tools_deny: tuple[str, ...] = ()
    output: str = ""


def _personas_dir() -> Path:
    return Path(os.getenv("ANCILLA_PERSONAS_DIR", str(DEFAULT_PERSONAS_DIR)))


def _from_data(name: str, data: dict[str, Any]) -> PersonaSpec:
    goals = data.get("goals")
    skills = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    preferred = skills.get("preferred") if isinstance(skills, dict) else []
    memory = data.get("memory") if isinstance(data.get("memory"), dict) else {}
    read = memory.get("read") if isinstance(memory, dict) else None
    tools = data.get("tools") if isinstance(data.get("tools"), dict) else {}
    deny = tools.get("deny") if isinstance(tools, dict) else []
    return PersonaSpec(
        name=str(data.get("name") or name),
        role=str(data.get("role") or "").strip(),
        goals=tuple(str(x) for x in goals) if isinstance(goals, list) else (),
        preferred_skills=tuple(str(x) for x in preferred) if isinstance(preferred, list) else (),
        memory_read=tuple(str(x) for x in read)
        if isinstance(read, list)
        else ("user_model", "episodic"),
        tools_deny=tuple(str(x) for x in deny) if isinstance(deny, list) else (),
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


def get_active_persona() -> PersonaSpec:
    return load_persona(_persona_name)


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
    global _persona_name
    _ = kwargs
    key = (name or "").strip()
    if not key:
        return "Error: name is required."
    names = list_persona_names()
    if key not in names:
        return f"Error: unknown persona: {key}. Available: {', '.join(names)}"
    _persona_name = key
    return f"Persona set to {key}."


def tool_denied_by_persona(tool_name: str) -> bool:
    if tool_name in _ALWAYS_ALLOW:
        return False
    return tool_name in get_active_persona().tools_deny
