"""Ancilla インストールルートと runtime パス。"""

from __future__ import annotations

import os
from pathlib import Path


def get_root() -> Path:
    """ANCILLA_ROOT があればそれ、無ければ cwd（開発用）。"""
    raw = (os.getenv("ANCILLA_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def get_home(root: Path | None = None) -> Path:
    raw = (os.getenv("ANCILLA_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (root or get_root()) / "data" / "home"


def get_workspace(root: Path | None = None) -> Path:
    raw = (os.getenv("ANCILLA_WORKSPACE_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return get_home(root) / "workspace"


def template_workspace(root: Path | None = None) -> Path:
    return (root or get_root()) / "workspace"


def ensure_workspace(root: Path | None = None) -> Path:
    r = root or get_root()
    dest = get_workspace(r)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "skills").mkdir(parents=True, exist_ok=True)
    (dest / ".trash").mkdir(parents=True, exist_ok=True)
    src = template_workspace(r)
    for name in ("AGENT.md", "AGENT.native.md"):
        target = dest / name
        source = src / name
        if not target.exists() and source.is_file():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    if dest.resolve() != src.resolve() and src.is_dir():
        for name in ("USER.md", "NOTE.md"):
            target = dest / name
            source = src / name
            if not target.exists() and source.is_file():
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        src_skills = src / "skills"
        dest_skills = dest / "skills"
        if src_skills.is_dir():
            for child in src_skills.iterdir():
                if not child.is_dir() or child.name.startswith("."):
                    continue
                skill_md = child / "SKILL.md"
                out = dest_skills / child.name / "SKILL.md"
                if skill_md.is_file() and not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(skill_md.read_text(encoding="utf-8"), encoding="utf-8")
    if not (dest / "USER.md").exists():
        (dest / "USER.md").write_text("# ユーザーについて\n", encoding="utf-8")
    if not (dest / "NOTE.md").exists():
        (dest / "NOTE.md").write_text("# メモ\n", encoding="utf-8")
    os.environ["ANCILLA_WORKSPACE_DIR"] = str(dest)
    return dest


def run_dir(root: Path | None = None) -> Path:
    return (root or get_root()) / "data" / "run"


def logs_dir(root: Path | None = None) -> Path:
    return (root or get_root()) / "data" / "logs"


def pid_path(name: str, root: Path | None = None) -> Path:
    return run_dir(root) / f"{name}.pid"


def log_path(name: str, root: Path | None = None) -> Path:
    return logs_dir(root) / f"{name}.log"


def ensure_runtime_dirs(root: Path | None = None) -> None:
    r = root or get_root()
    run_dir(r).mkdir(parents=True, exist_ok=True)
    logs_dir(r).mkdir(parents=True, exist_ok=True)
