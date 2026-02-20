"""
workspace 内のファイル読み書き。パスは workspace 以下に制限する。
"""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT = Path(os.getenv("ANCILLA_WORKSPACE_DIR", "workspace"))


def _resolve(path_str: str) -> Path | None:
    """
    パスを workspace 内に正規化する。外へ出る場合は None を返す。
    """
    root = WORKSPACE_ROOT.resolve()
    p = (root / path_str).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    return p


def read_file(path: str, **kwargs: object) -> str:
    """
    workspace 内のファイルを読み込む。
    path: workspace からの相対パス（例: memory/NOTE.md）
    """
    _ = kwargs
    resolved = _resolve(path)
    if resolved is None:
        return "Error: パスは workspace 以下のみ許可されています。"
    if not resolved.exists():
        return f"Error: ファイルが存在しません: {path}"
    try:
        return resolved.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error: 読み込みに失敗しました: {e}"


def write_file(path: str, content: str, **kwargs: object) -> str:
    """
    workspace 内のファイルに書き込む。
    path: workspace からの相対パス（例: memory/NOTE.md）
    content: 書き込む内容
    """
    _ = kwargs
    resolved = _resolve(path)
    if resolved is None:
        return "Error: パスは workspace 以下のみ許可されています。"
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return f"書き込み完了: {path}"
    except OSError as e:
        return f"Error: 書き込みに失敗しました: {e}"
