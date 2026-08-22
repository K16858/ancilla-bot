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
