"""Trial skill run logging, promote, and rollback (workspace skills only)."""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

import yaml

from ancilla_bot.cli.paths import get_workspace
from ancilla_bot.heartbeat.db import (
    latest_skill_promotion,
    list_skill_runs,
    record_skill_run,
    save_skill_promotion,
)
from ancilla_bot.skills.loader import SkillMeta, list_skills

_loaded_skills: ContextVar[tuple[tuple[str, int], ...]] = ContextVar(
    "loaded_skills", default=()
)
_had_tool_failure: ContextVar[bool] = ContextVar("skill_run_tool_failure", default=False)

_PROMOTE_SUCCESS_N = 3


def note_skill_loaded(name: str, version: int) -> None:
    key = (name, int(version))
    current = _loaded_skills.get()
    if key in current:
        return
    _loaded_skills.set(current + (key,))


def snapshot_loaded_skills() -> tuple[tuple[str, int], ...]:
    return _loaded_skills.get()


def restore_loaded_skills(loads: list[tuple[str, int]] | tuple[tuple[str, int], ...]) -> None:
    _loaded_skills.set(tuple((str(n), int(v)) for n, v in loads))


def note_tool_failure() -> None:
    _had_tool_failure.set(True)


def reset_skill_run_tracking() -> tuple[object, object]:
    t1 = _loaded_skills.set(())
    t2 = _had_tool_failure.set(False)
    return t1, t2


def restore_skill_run_tracking(tokens: tuple[object, object]) -> None:
    _loaded_skills.reset(tokens[0])  # type: ignore[arg-type]
    _had_tool_failure.reset(tokens[1])  # type: ignore[arg-type]


def flush_skill_runs(run_id: str, *, completed: bool) -> None:
    loaded = _loaded_skills.get()
    if not loaded:
        return
    outcome = "failure" if (not completed or _had_tool_failure.get()) else "success"
    for name, version in loaded:
        record_skill_run(name=name, version=version, run_id=run_id, outcome=outcome)


def _workspace_skill_path(name: str) -> Path | None:
    root = get_workspace() / "skills"
    for child in root.iterdir() if root.is_dir() else []:
        skill_md = child / "SKILL.md"
        if not child.is_dir() or not skill_md.is_file():
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        meta_name = child.name
        if text.startswith("---"):
            rest = text[3:].lstrip("\n")
            end = rest.find("\n---")
            if end >= 0:
                data = yaml.safe_load(rest[:end]) or {}
                if isinstance(data, dict) and data.get("name"):
                    meta_name = str(data["name"]).strip() or meta_name
        if meta_name == name:
            return skill_md
    return None


def _find_workspace_skill(name: str) -> SkillMeta | None:
    path = _workspace_skill_path(name)
    if path is None:
        return None
    for skill in list_skills():
        if skill.name == name and skill.path.resolve() == path.resolve():
            return skill
    return None


def _set_frontmatter_status(text: str, status: str) -> str:
    if not text.startswith("---"):
        return f"---\nstatus: {status}\n---\n{text}"
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return f"---\nstatus: {status}\n---\n{text}"
    raw = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        data = {}
    data["status"] = status
    fm = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{fm}\n---\n{body}"


def promote_skill(name: str) -> str:
    key = (name or "").strip()
    if not key:
        return "Error: name is required."
    skill = _find_workspace_skill(key)
    if skill is None:
        return f"Error: workspace skill not found: {key}"
    if skill.status != "trial":
        return f"Error: skill {key} is not trial (status={skill.status})."
    runs = list_skill_runs(key, version=skill.version, limit=_PROMOTE_SUCCESS_N)
    if len(runs) < _PROMOTE_SUCCESS_N:
        return (
            f"Error: need {_PROMOTE_SUCCESS_N} recent runs for {key} v{skill.version}; "
            f"have {len(runs)}."
        )
    if any(r["outcome"] != "success" for r in runs):
        return f"Error: recent runs for {key} include failures; cannot promote."
    path = skill.path
    try:
        body_before = path.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error: could not read skill: {e}"
    save_skill_promotion(name=key, version=skill.version, body_before=body_before)
    try:
        path.write_text(_set_frontmatter_status(body_before, "active"), encoding="utf-8")
    except OSError as e:
        return f"Error: could not write skill: {e}"
    return f"Promoted workspace skill {key} v{skill.version} to active."


def rollback_skill(name: str) -> str:
    key = (name or "").strip()
    if not key:
        return "Error: name is required."
    path = _workspace_skill_path(key)
    if path is None:
        return f"Error: workspace skill not found: {key}"
    promo = latest_skill_promotion(key)
    if promo is None:
        return f"Error: no promotion snapshot for {key}."
    body = _set_frontmatter_status(str(promo["body_before"]), "trial")
    try:
        path.write_text(body, encoding="utf-8")
    except OSError as e:
        return f"Error: could not write skill: {e}"
    return f"Rolled back workspace skill {key} to trial (from promotion id={promo['id']})."
