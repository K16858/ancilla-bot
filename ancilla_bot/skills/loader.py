"""
SKILL.md の発見と読み込み。
同梱 skills/ のあと workspace/skills/ を読み、同名は workspace を優先する。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_SKILLS_DIR = Path(os.getenv("ANCILLA_SKILLS_DIR", "skills"))
DEFAULT_WORKSPACE_DIR = Path(os.getenv("ANCILLA_WORKSPACE_DIR", "workspace"))


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path
    body: str


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    rest = text[3:].lstrip("\n")
    end = rest.find("\n---")
    if end < 0:
        return {}, text
    raw = rest[:end]
    body = rest[end + 4 :].lstrip("\n")
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        return {}, text
    return data, body


def _load_skill_file(path: Path, dir_name: str) -> SkillMeta | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _split_frontmatter(text)
    name = str(meta.get("name") or dir_name).strip()
    description = str(meta.get("description") or "").strip()
    if not name:
        return None
    return SkillMeta(name=name, description=description, path=path, body=body.strip())


def _scan_dir(root: Path) -> dict[str, SkillMeta]:
    found: dict[str, SkillMeta] = {}
    if not root.is_dir():
        return found
    for child in sorted(root.iterdir()):
        skill_md = child / "SKILL.md"
        if not child.is_dir() or not skill_md.is_file():
            continue
        skill = _load_skill_file(skill_md, child.name)
        if skill is not None:
            found[skill.name] = skill
    return found


def list_skills() -> list[SkillMeta]:
    bundled = Path(os.getenv("ANCILLA_SKILLS_DIR", str(DEFAULT_SKILLS_DIR)))
    workspace = Path(os.getenv("ANCILLA_WORKSPACE_DIR", str(DEFAULT_WORKSPACE_DIR))) / "skills"
    merged = _scan_dir(bundled)
    merged.update(_scan_dir(workspace))
    return sorted(merged.values(), key=lambda s: s.name)


def read_skill(name: str, **kwargs: object) -> str:
    _ = kwargs
    key = (name or "").strip()
    if not key:
        return "Error: name is required."
    for skill in list_skills():
        if skill.name == key:
            return skill.body or skill.description
    return f"Error: unknown skill: {key}"


def format_skills_catalog() -> str:
    skills = list_skills()
    if not skills:
        return ""
    lines = ["## Available skills", ""]
    for skill in skills:
        desc = skill.description or "(no description)"
        lines.append(f"- {skill.name}: {desc}")
    return "\n".join(lines)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        bundled = Path(tmp) / "bundled"
        ws = Path(tmp) / "ws"
        (bundled / "alpha").mkdir(parents=True)
        (bundled / "shared").mkdir(parents=True)
        (ws / "skills" / "shared").mkdir(parents=True)
        (ws / "skills" / "beta").mkdir(parents=True)
        (bundled / "alpha" / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: Bundled alpha.\n---\nAlpha body.\n",
            encoding="utf-8",
        )
        (bundled / "shared" / "SKILL.md").write_text(
            "---\nname: shared\ndescription: Bundled shared.\n---\nBundled body.\n",
            encoding="utf-8",
        )
        (ws / "skills" / "shared" / "SKILL.md").write_text(
            "---\nname: shared\ndescription: Workspace shared.\n---\nWorkspace body.\n",
            encoding="utf-8",
        )
        (ws / "skills" / "beta" / "SKILL.md").write_text(
            "---\ndescription: Workspace beta.\n---\nBeta body.\n",
            encoding="utf-8",
        )
        os.environ["ANCILLA_SKILLS_DIR"] = str(bundled)
        os.environ["ANCILLA_WORKSPACE_DIR"] = str(ws)
        names = [s.name for s in list_skills()]
        assert names == ["alpha", "beta", "shared"], names
        assert read_skill("shared") == "Workspace body."
        assert read_skill("missing").startswith("Error:")
        catalog = format_skills_catalog()
        assert "alpha: Bundled alpha." in catalog
        assert "Workspace shared." in catalog
        print("ok")
