"""
シェルコマンドを workspace をカレントディレクトリとして実行する。
ANCILLA_SANDBOX=docker の場合はコンテナ内で実行する。
"""

from __future__ import annotations

import os
import subprocess

from ancilla_bot.tools.workspace_io import WORKSPACE_ROOT

DEFAULT_TIMEOUT_SEC = 60
MAX_TIMEOUT_SEC = 300
MAX_OUTPUT_CHARS = 20_000
SANDBOX_MODE = os.getenv("ANCILLA_SANDBOX", "none").strip().lower()
SANDBOX_IMAGE = os.getenv("ANCILLA_SANDBOX_IMAGE", "ancilla-sandbox")


def _command_head(command: str) -> str:
    parts = command.strip().split()
    if not parts:
        return ""
    token = parts[0]
    return token.split("/")[-1].split("\\")[-1].lower()


def _check_allowlist(command: str) -> str | None:
    raw = os.getenv("ANCILLA_BASH_ALLOWLIST", "").strip()
    if not raw:
        return None
    allowed = {item.strip().lower() for item in raw.split(",") if item.strip()}
    head = _command_head(command)
    if head not in allowed:
        return f"Error: command '{head}' is not allowed by ANCILLA_BASH_ALLOWLIST."
    return None


def _format_output(result: subprocess.CompletedProcess[str]) -> str:
    out = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        out = f"[exit {result.returncode}]\n{out}"
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
    return out.strip() or "(no output)"


def _run_subprocess(
    command: str,
    *,
    cwd: str,
    timeout_sec: int,
    stdin_text: str | None,
) -> str:
    result = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        input=stdin_text,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    return _format_output(result)


def _run_docker(
    command: str,
    *,
    cwd: str,
    timeout_sec: int,
    stdin_text: str | None,
) -> str:
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{cwd}:/workspace:rw",
        "-w",
        "/workspace",
        "--memory=512m",
        "--cpus=1.0",
        "--network=none",
        SANDBOX_IMAGE,
        "sh",
        "-c",
        command,
    ]
    result = subprocess.run(
        docker_cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        input=stdin_text,
    )
    return _format_output(result)


def bash(
    command: str,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    stdin_text: str | None = None,
    **kwargs: object,
) -> str:
    """
    シェルコマンドを実行して stdout + stderr を返す。
    cwd は workspace ルート（相対パスはここを起点にする）。
    """
    _ = kwargs
    command = (command or "").strip()
    if not command:
        return "Error: command を指定してください。"

    denied = _check_allowlist(command)
    if denied:
        return denied

    timeout_sec = min(max(int(timeout_sec), 1), MAX_TIMEOUT_SEC)
    cwd = str(WORKSPACE_ROOT.resolve())

    try:
        if SANDBOX_MODE == "docker":
            return _run_docker(
                command,
                cwd=cwd,
                timeout_sec=timeout_sec,
                stdin_text=stdin_text,
            )
        return _run_subprocess(
            command,
            cwd=cwd,
            timeout_sec=timeout_sec,
            stdin_text=stdin_text,
        )
    except subprocess.TimeoutExpired:
        return f"Error: タイムアウト（{timeout_sec} 秒）しました。"
    except OSError as e:
        return f"Error: 実行に失敗しました: {e}"
