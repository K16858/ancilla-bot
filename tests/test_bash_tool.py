import subprocess
import sys
from pathlib import Path

import pytest

from ancilla_bot.tools import bash as bash_mod


@pytest.fixture(autouse=True)
def workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(bash_mod, "SANDBOX_MODE", "none")
    monkeypatch.delenv("ANCILLA_BASH_ALLOWLIST", raising=False)
    return tmp_path


PY = f'"{sys.executable}"'


def test_runs_in_workspace_root(workspace: Path):
    out = bash_mod.bash(f'{PY} -c "import os; print(os.getcwd())"')
    assert Path(out).resolve() == workspace.resolve()


def test_nonzero_exit_and_stderr_are_reported():
    out = bash_mod.bash(f'{PY} -c "import sys; sys.stderr.write(\'boom\'); sys.exit(3)"')
    assert out.startswith("[exit 3]")
    assert "boom" in out


def test_stdin_is_passed():
    assert bash_mod.bash(f'{PY} -c "print(input()[::-1])"', stdin_text="abc\n") == "cba"


def test_empty_command_is_rejected():
    assert bash_mod.bash("   ").startswith("Error")


def test_allowlist_matches_basename_case_insensitively(monkeypatch):
    monkeypatch.setenv("ANCILLA_BASH_ALLOWLIST", "Python, echo")
    assert bash_mod._check_allowlist("/usr/bin/python -V") is None
    assert bash_mod._check_allowlist(r"C:\tools\PYTHON -V") is None
    denied = bash_mod.bash("rm -rf .")
    assert "'rm' is not allowed" in denied


def test_timeout_is_clamped_and_reported(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(bash_mod.subprocess, "run", fake_run)
    assert "タイムアウト（300 秒）" in bash_mod.bash("sleep 1", timeout_sec=10_000)
    assert seen["timeout"] == bash_mod.MAX_TIMEOUT_SEC
    bash_mod.bash("sleep 1", timeout_sec=0)
    assert seen["timeout"] == 1


def test_output_is_truncated():
    result = subprocess.CompletedProcess("x", 0, stdout="a" * (bash_mod.MAX_OUTPUT_CHARS + 5), stderr="")
    out = bash_mod._format_output(result)
    assert out.endswith("... (output truncated)")
    assert len(out) < bash_mod.MAX_OUTPUT_CHARS + 30
    assert bash_mod._format_output(subprocess.CompletedProcess("x", 0, stdout="", stderr="")) == "(no output)"


def test_docker_sandbox_isolates_network_and_mounts_workspace(monkeypatch, workspace: Path):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(bash_mod, "SANDBOX_MODE", "docker")
    monkeypatch.setattr(bash_mod.subprocess, "run", fake_run)
    assert bash_mod.bash("ls") == "ok"
    cmd = seen["cmd"]
    assert "--network=none" in cmd
    assert f"{workspace.resolve()}:/workspace:rw" in cmd
    assert cmd[-3:] == ["sh", "-c", "ls"]
