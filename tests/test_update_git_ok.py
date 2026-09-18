from pathlib import Path

from ancilla_bot.cli.commands.update import _git_ok


def _git(root: Path, *args: str) -> None:
    import subprocess

    r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_git_ok_ignores_untracked_workspace_files(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "README").write_text("x", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")

    ws = root / "workspace"
    ws.mkdir()
    (ws / "MEMORY.md").write_text("user note", encoding="utf-8")

    assert _git_ok(root) is None


def test_git_ok_rejects_modified_tracked_file(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    tracked = root / "tracked.txt"
    tracked.write_text("a", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-m", "init")
    tracked.write_text("b", encoding="utf-8")

    reason = _git_ok(root)
    assert reason is not None
    assert "Dirty" in reason
