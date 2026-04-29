"""
pending.jsonl を複数プロセス・複数ポーラーから安全に取り出すための補助。

キュー本体を一時ファイルへ os.replace で移してから読むことで、
同一内容を二重に読み取る競合を避ける。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path


def take_pending_jsonl_lines(pending_path: Path) -> list[str]:
    """
    pending_path（例: .../pending.jsonl）をキューから切り離し、
    非空行（strip 済み）のリストを返す。キューが無い・取り出せないときは []。

    取り出し後、元ファイルは存在しない（空のキュー）になる。
    読み取りに失敗した場合は可能な限り元パスへ戻す。
    """
    if not pending_path.is_file():
        return []
    parent = pending_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f"pending._stg.{uuid.uuid4().hex}.jsonl"
    try:
        os.replace(pending_path, staging)
    except OSError:
        return []
    try:
        raw = staging.read_text(encoding="utf-8")
    except OSError:
        try:
            os.replace(staging, pending_path)
        except OSError:
            pass
        return []
    try:
        staging.unlink(missing_ok=True)
    except OSError:
        pass
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]
