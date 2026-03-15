"""
workspace 内の Python スクリプトをサブプロセスで実行する。タイムアウト・stdin 対応。
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

from ancilla_bot.tools.workspace_io import WORKSPACE_ROOT, _resolve

DEFAULT_TIMEOUT_SEC = 60
MAX_TIMEOUT_SEC = 300
MAX_OUTPUT_CHARS = 20_000


def run_python_script(
    path: str,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    args: list[str] | None = None,
    stdin_text: str | None = None,
    **kwargs: object,
) -> str:
    """
    workspace 内の .py ファイルを subprocess で実行し、stdout と stderr を返す。
    path: workspace からの相対パス（例: scripts/hello.py）
    timeout_sec: タイムアウト秒。上限は MAX_TIMEOUT_SEC。
    args: スクリプトに渡す引数リスト（例: ["--input", "data.txt"]）
    stdin_text: 標準入力として渡す文字列（省略可）
    """
    _ = kwargs
    path_str = (path or "").strip()
    if not path_str.lower().endswith(".py"):
        return "Error: 有効な Python ファイルを指定してください。（.py のみ許可）"
    resolved = _resolve(path_str)
    if resolved is None:
        return "Error: パスは workspace 以下のみ許可されています。"
    if not resolved.exists():
        return "Error: 有効な Python ファイルを指定してください。"
    if not resolved.is_file():
        return "Error: 有効な Python ファイルを指定してください。"

    timeout_sec = min(max(timeout_sec, 1), MAX_TIMEOUT_SEC)
    cmd = [sys.executable, str(resolved)]
    if args:
        cmd.extend(str(a) for a in args[:32])
    root = WORKSPACE_ROOT.resolve()
    try:
        result = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            input=stdin_text,
        )
        out = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            out = f"[exit code {result.returncode}]\n{out}"
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + "\n... (output truncated)"
        return out.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: タイムアウト（{timeout_sec} 秒）しました。"
    except OSError as e:
        return f"Error: 実行に失敗しました: {e}"
