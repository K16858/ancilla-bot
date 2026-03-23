"""
シェルコマンドを workspace をカレントディレクトリとして実行する。
Linux/macOS では /bin/sh、Windows では cmd.exe 経由。
"""

from __future__ import annotations

import os
import subprocess

from ancilla_bot.tools.workspace_io import WORKSPACE_ROOT

DEFAULT_TIMEOUT_SEC = 60
MAX_TIMEOUT_SEC = 300
MAX_OUTPUT_CHARS = 20_000


def bash(
    command: str,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    stdin_text: str | None = None,
    **kwargs: object,
) -> str:
    """
    シェルコマンドを実行して stdout + stderr を返す。
    cwd は workspace ルート（相対パスはここを起点にする）。
    timeout_sec: 上限は MAX_TIMEOUT_SEC（省略時 60 秒）。
    """
    _ = kwargs
    command = (command or "").strip()
    if not command:
        return "Error: command を指定してください。"

    timeout_sec = min(max(int(timeout_sec), 1), MAX_TIMEOUT_SEC)
    cwd = WORKSPACE_ROOT.resolve()

    try:
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
        out = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            out = f"[exit {result.returncode}]\n{out}"
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: タイムアウト（{timeout_sec} 秒）しました。"
    except OSError as e:
        return f"Error: 実行に失敗しました: {e}"
