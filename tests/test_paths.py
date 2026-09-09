from pathlib import Path

from ancilla_bot.cli.paths import (
    ensure_workspace,
    get_root,
    get_workspace,
    log_path,
    pid_path,
)


def test_get_root_prefers_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_ROOT", str(tmp_path))
    assert get_root() == tmp_path.resolve()


def test_get_workspace_prefers_env(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    monkeypatch.delenv("ANCILLA_ROOT", raising=False)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    assert get_workspace() == ws.resolve()


def test_pid_and_log_paths(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_ROOT", str(tmp_path))
    assert pid_path("core") == (tmp_path / "data" / "run" / "core.pid").resolve()
    assert log_path("core") == (tmp_path / "data" / "logs" / "core.log").resolve()


def test_ensure_workspace_copies_templates(tmp_path: Path, monkeypatch):
    src = tmp_path / "workspace"
    src.mkdir()
    (src / "AGENT.md").write_text("agent", encoding="utf-8")
    (src / "USER.md").write_text("user", encoding="utf-8")
    monkeypatch.setenv("ANCILLA_ROOT", str(tmp_path))
    monkeypatch.delenv("ANCILLA_WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("ANCILLA_HOME", raising=False)
    dest = ensure_workspace()
    assert (dest / "AGENT.md").read_text(encoding="utf-8") == "agent"
    assert (dest / "USER.md").read_text(encoding="utf-8") == "user"
    assert (dest / "skills").is_dir()
    assert (dest / ".trash").is_dir()
