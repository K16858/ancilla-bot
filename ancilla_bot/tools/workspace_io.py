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


DEFAULT_READ_MAX_LINES = 2000
MAX_READ_LINES_LIMIT = 10000


def read_file(path: str, max_lines: int | None = None, **kwargs: object) -> str:
    """
    workspace 内のファイルを読み込む。
    path: workspace からの相対パス（例: NOTE.md）
    max_lines: 最大行数。超過分は切り捨てて末尾に "... (truncated, max_lines=N)" を付与。省略時は DEFAULT_READ_MAX_LINES。
    """
    _ = kwargs
    resolved = _resolve(path)
    if resolved is None:
        return "Error: パスは workspace 以下のみ許可されています。"
    if not resolved.exists():
        return f"Error: ファイルが存在しません: {path}"
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as e:
        return f"Error: 読み込みに失敗しました: {e}"
    limit = max_lines if max_lines is not None else DEFAULT_READ_MAX_LINES
    limit = min(max(limit, 1), MAX_READ_LINES_LIMIT)
    lines = text.splitlines(keepends=True)
    if len(lines) <= limit:
        return text
    head = "".join(lines[:limit])
    return head + f"\n... (truncated, max_lines={limit})"


DEFAULT_LIST_MAX_ENTRIES = 100
DEFAULT_LIST_MAX_DEPTH = 4
MAX_LIST_ENTRIES_LIMIT = 500
MAX_LIST_DEPTH_LIMIT = 5

MAX_EDIT_CONTENT_CHARS = 10_000


def list_workspace(
    path: str = "",
    max_entries: int = DEFAULT_LIST_MAX_ENTRIES,
    max_depth: int = DEFAULT_LIST_MAX_DEPTH,
    **kwargs: object,
) -> str:
    """
    workspace 内のファイル・ディレクトリ一覧を返す。
    path: workspace からの相対パス（省略時はルート）。
    返すエントリは workspace ルートからの相対パス（read_file にそのまま渡せる）。
    """
    _ = kwargs
    path_str = path.strip() or "."
    resolved = _resolve(path_str)
    if resolved is None:
        return "Error: パスは workspace 以下のみ許可されています。"
    if not resolved.exists():
        return f"Error: パスが存在しません: {path_str}"
    if resolved.is_file():
        try:
            rel = resolved.relative_to(WORKSPACE_ROOT.resolve())
            return str(rel)
        except ValueError:
            return "Error: パスは workspace 以下のみ許可されています。"

    max_entries = min(max(max_entries, 1), MAX_LIST_ENTRIES_LIMIT)
    max_depth = min(max(max_depth, 0), MAX_LIST_DEPTH_LIMIT)
    root = WORKSPACE_ROOT.resolve()
    collected: list[str] = []

    def _scan(current: Path, depth: int) -> None:
        if depth > max_depth or len(collected) >= max_entries:
            return
        try:
            for child in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if len(collected) >= max_entries:
                    return
                try:
                    rel = child.relative_to(root)
                    name = str(rel)
                except ValueError:
                    continue
                if child.is_dir():
                    collected.append(name + "/")
                    if depth < max_depth:
                        _scan(child, depth + 1)
                else:
                    collected.append(name)
        except OSError:
            pass

    start_depth = 0
    try:
        rel_root = resolved.relative_to(root)
        if rel_root != Path("."):
            start_depth = len(rel_root.parts)
    except ValueError:
        pass
    _scan(resolved, start_depth)

    if not collected:
        return "(空)"
    return "\n".join(collected)


def edit_file_safe(
    path: str,
    operation: str,
    content: str | None = None,
    old: str | None = None,
    new: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    **kwargs: object,
) -> str:
    """
    追記（append）または置換（replace）のみ。全上書きは禁止。
    operation: "append" | "replace"
    append: content をファイル末尾に追加。ファイルが無ければ新規作成。
    replace: 文字列置換なら old と new。行範囲なら start_line, end_line (1-based), new。
    """
    _ = kwargs
    resolved = _resolve(path)
    if resolved is None:
        return "Error: パスは workspace 以下のみ許可されています。"
    if operation not in ("append", "replace"):
        return "Error: operation は append または replace を指定してください。"

    if operation == "append":
        if content is None:
            return "Error: append の場合は content を指定してください。"
        if len(content) > MAX_EDIT_CONTENT_CHARS:
            return f"Error: content は {MAX_EDIT_CONTENT_CHARS} 文字以内にしてください。"
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with resolved.open("a", encoding="utf-8") as f:
                f.write(content)
            return f"追記完了: {path}"
        except OSError as e:
            return f"Error: 書き込みに失敗しました: {e}"

    if not resolved.exists():
        return "Error: ファイルが存在しません。append を使って作成してください。"
    if start_line is not None and end_line is not None:
        if new is None:
            return "Error: 行範囲置換の場合は new を指定してください。"
        if len(new) > MAX_EDIT_CONTENT_CHARS:
            return f"Error: new は {MAX_EDIT_CONTENT_CHARS} 文字以内にしてください。"
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as e:
            return f"Error: 読み込みに失敗しました: {e}"
        lines = text.splitlines(keepends=True)
        if not lines and (start_line != 1 or end_line != 0):
            return "Error: ファイルが空です。"
        n = len(lines)
        if start_line < 1 or end_line < 1 or start_line > n or end_line > n or start_line > end_line:
            return "Error: 行範囲が不正です。"
        before = "".join(lines[: start_line - 1])
        after = "".join(lines[end_line:])
        try:
            resolved.write_text(before + new + ("\n" if new and not new.endswith("\n") else "") + after, encoding="utf-8")
        except OSError as e:
            return f"Error: 書き込みに失敗しました: {e}"
        return f"置換完了（行 {start_line}-{end_line}）: {path}"
    else:
        if old is None or new is None:
            return "Error: replace の場合は old と new を指定してください。"
        if len(old) > MAX_EDIT_CONTENT_CHARS or len(new) > MAX_EDIT_CONTENT_CHARS:
            return f"Error: old / new は {MAX_EDIT_CONTENT_CHARS} 文字以内にしてください。"
        if not old.strip():
            return "Error: 置換対象が見つかりません。"
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as e:
            return f"Error: 読み込みに失敗しました: {e}"
        if old not in text:
            return "Error: 置換対象が見つかりません。"
        new_text = text.replace(old, new, 1)
        try:
            resolved.write_text(new_text, encoding="utf-8")
        except OSError as e:
            return f"Error: 書き込みに失敗しました: {e}"
        return f"置換完了: {path}"


def write_file(path: str, content: str, **kwargs: object) -> str:
    """
    workspace 内のファイルに書き込む。
    path: workspace からの相対パス（例: NOTE.md）
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
