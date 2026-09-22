from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODES_DIR = Path(os.getenv("ANCILLA_MODES_DIR", "modes"))
# ponytail: one mode for the process. Per-conversation mode if overlapping runs must differ.
_mode_name = "general"


@dataclass(frozen=True)
class ModeSpec:
    name: str
    reasoning_policy: str = "standard"
    planning_depth: str = "medium"
    skill_priority: tuple[str, ...] = ()
    memory_scope: tuple[str, ...] = ("user_model", "episodic")
    output_policy: str = "default"
    proactive: str = "medium"


def _modes_dir() -> Path:
    return Path(os.getenv("ANCILLA_MODES_DIR", str(DEFAULT_MODES_DIR)))


def _from_data(name: str, data: dict[str, Any]) -> ModeSpec:
    caps = data.get("skill_priority")
    scope = data.get("memory_scope")
    return ModeSpec(
        name=str(data.get("name") or name),
        reasoning_policy=str(data.get("reasoning_policy") or "standard"),
        planning_depth=str(data.get("planning_depth") or "medium"),
        skill_priority=tuple(str(x) for x in caps) if isinstance(caps, list) else (),
        memory_scope=tuple(str(x) for x in scope) if isinstance(scope, list) else ("user_model", "episodic"),
        output_policy=str(data.get("output_policy") or "default"),
        proactive=str(data.get("proactive") or "medium"),
    )


def list_mode_names() -> list[str]:
    root = _modes_dir()
    if not root.is_dir():
        return ["general"]
    names = sorted(p.stem for p in root.glob("*.yaml") if p.is_file())
    return names or ["general"]


def load_mode(name: str) -> ModeSpec:
    key = (name or "general").strip() or "general"
    path = _modes_dir() / f"{key}.yaml"
    if not path.is_file():
        path = _modes_dir() / "general.yaml"
    if not path.is_file():
        return ModeSpec(name="general")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return ModeSpec(name="general")
    if not isinstance(data, dict):
        return ModeSpec(name="general")
    return _from_data(key, data)


def get_active_mode() -> ModeSpec:
    return load_mode(_mode_name)


def format_mode_overlay() -> str:
    spec = get_active_mode()
    lines = [
        f"## Active mode: {spec.name}",
        f"- reasoning: {spec.reasoning_policy}",
        f"- planning_depth: {spec.planning_depth}",
        f"- output: {spec.output_policy}",
        f"- proactive: {spec.proactive}",
        f"- memory_scope: {', '.join(spec.memory_scope)}",
    ]
    if spec.skill_priority:
        lines.append("- skill_priority: " + ", ".join(spec.skill_priority))
    return "\n".join(lines)


def set_mode(name: str, **kwargs: object) -> str:
    global _mode_name
    _ = kwargs
    key = (name or "").strip()
    if not key:
        return "Error: name is required."
    names = list_mode_names()
    if key not in names:
        return f"Error: unknown mode: {key}. Available: {', '.join(names)}"
    _mode_name = key
    return f"Mode set to {key}."
