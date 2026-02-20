"""
会話ログを JSONL として保存するシンプルなセッションストア
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable


Message = Dict[str, str]

DEFAULT_SESSIONS_DIR = Path(os.getenv("ANCILLA_SESSIONS_DIR", "data/sessions"))


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def append_messages(
    session_id: str,
    messages: Iterable[Message],
    *,
    sessions_dir: Path | None = None,
) -> None:
    """
    メッセージを JSONL 形式で追記する。
    1 行 1 メッセージ。
    """
    msgs = list(messages)
    if not msgs:
        return

    base_dir = sessions_dir or DEFAULT_SESSIONS_DIR
    _ensure_dir(base_dir)
    path = base_dir / f"{session_id}.jsonl"

    now = datetime.utcnow().isoformat()
    with path.open("a", encoding="utf-8") as f:
        for m in msgs:
            record = {
                "timestamp": now,
                "role": m.get("role", ""),
                "content": m.get("content", ""),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
