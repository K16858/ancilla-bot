"""ancilla update / update --check。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from ancilla_bot.cli import process, ux
from ancilla_bot.cli.paths import get_root


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def _git_ok(root: Path) -> str | None:
    """問題があれば理由文字列、なければ None。"""
    if not (root / ".git").exists():
        return "Not a git checkout. Update requires a git-managed install."
    st = _run(["git", "status", "--porcelain"], cwd=root)
    if st.returncode != 0:
        return st.stderr.strip() or "git status failed"
    if st.stdout.strip():
        return "Dirty working tree. Commit or stash local changes first."
    return None


def cmd_update(args: argparse.Namespace) -> int:
    root = get_root()
    if getattr(args, "check", False):
        return _check(root)

    running = process.any_managed_running()
    if running:
        return ux.fail(
            "Ancilla is currently running.",
            cause=f"Managed: {', '.join(running)}",
            next_cmds=["ancilla stop", "ancilla update", "ancilla start"],
        )

    reason = _git_ok(root)
    if reason:
        return ux.fail("Cannot update.", cause=reason, next_cmds=["git status", "ancilla doctor"])

    print(f"Updating in {root} ...")
    fetch = _run(["git", "fetch", "--quiet"], cwd=root)
    if fetch.returncode != 0:
        return ux.fail("git fetch failed.", cause=fetch.stderr.strip(), next_cmds=["ancilla doctor"])

    pull = _run(["git", "pull", "--ff-only"], cwd=root)
    if pull.returncode != 0:
        return ux.fail(
            "git pull --ff-only failed.",
            cause=(pull.stderr or pull.stdout).strip(),
            next_cmds=["git status"],
        )
    print(pull.stdout.strip() or "Already up to date.")

    pip = _run([sys.executable, "-m", "pip", "install", "-e", "."], cwd=root)
    if pip.returncode != 0:
        return ux.fail("pip install failed.", cause=pip.stderr.strip()[-2000:], next_cmds=["ancilla doctor"])

    ver = _run([sys.executable, "-m", "ancilla_bot.cli", "version"], cwd=root)
    print()
    print(ver.stdout.strip() or "Update complete.")
    print()
    print("Next:")
    print("  ancilla start")
    return 0


def _check(root: Path) -> int:
    if not (root / ".git").exists():
        return ux.fail("Not a git checkout.", next_cmds=["ancilla doctor"])
    cur = _run(["git", "rev-parse", "--short", "HEAD"], cwd=root)
    if cur.returncode != 0:
        return ux.fail("Cannot read HEAD.", cause=cur.stderr.strip())
    current = cur.stdout.strip()
    fetch = _run(["git", "fetch", "--quiet"], cwd=root)
    if fetch.returncode != 0:
        return ux.fail("git fetch failed.", cause=fetch.stderr.strip())

    upstream = "@{u}"
    remote = _run(["git", "rev-parse", "--short", upstream], cwd=root)
    if remote.returncode != 0:
        upstream = "origin/main"
        remote = _run(["git", "rev-parse", "--short", upstream], cwd=root)
    if remote.returncode != 0:
        return ux.fail("Cannot resolve upstream tip.", cause=remote.stderr.strip())
    latest = remote.stdout.strip()

    counts = _run(["git", "rev-list", "--left-right", "--count", f"HEAD...{upstream}"], cwd=root)
    ahead, behind = 0, 0
    if counts.returncode == 0:
        parts = counts.stdout.strip().split()
        if len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

    print(f"Current: {current}")
    print(f"Latest:  {latest}")
    print()
    if behind == 0 and ahead == 0:
        print("Already up to date.")
    elif behind == 0 and ahead > 0:
        print(f"Local is ahead by {ahead} commit(s).")
    else:
        print("Update available.")
        print()
        print("Next:")
        print("  ancilla stop")
        print("  ancilla update")
        print("  ancilla start")
    return 0


def cmd_version(_args: argparse.Namespace | None = None) -> int:
    root = get_root()
    try:
        from importlib.metadata import version

        ver = version("ancilla-bot")
    except Exception:
        ver = "0.1.0"
    commit = "unknown"
    if (root / ".git").exists():
        r = _run(["git", "rev-parse", "--short", "HEAD"], cwd=root)
        if r.returncode == 0:
            commit = r.stdout.strip()
    print(f"Ancilla {ver}")
    print(f"Commit: {commit}")
    print(f"Python: {sys.version.split()[0]}")
    return 0
