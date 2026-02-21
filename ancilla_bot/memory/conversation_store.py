"""
会話履歴の保存・読み込み
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

Message = dict[str, str]

DEFAULT_CONVERSATION_DIR = Path(os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation"))
ACTIVE_FILE = "active_history.jsonl"
OVERFLOW_FILE = "overflow.jsonl"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _path(filename: str) -> Path:
    base = Path(os.getenv("ANCILLA_CONVERSATION_DIR", str(DEFAULT_CONVERSATION_DIR)))
    return base / filename


def append_overflow(messages: Iterable[Message]) -> None:
    """
    オーバーフローしたメッセージを overflow.jsonl に追記する。
    """
    msgs = list(messages)
    if not msgs:
        return
    p = _path(OVERFLOW_FILE)
    _ensure_dir(p.parent)
    with p.open("a", encoding="utf-8") as f:
        for m in msgs:
            record = {"role": m.get("role", ""), "content": m.get("content", "")}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_active_history(history: list[Message]) -> None:
    """
    アクティブな会話履歴を active_history.jsonl に保存する（上書き）。
    """
    p = _path(ACTIVE_FILE)
    _ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as f:
        for m in history:
            record = {"role": m.get("role", ""), "content": m.get("content", "")}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_active_history() -> list[Message]:
    """
    active_history.jsonl から会話履歴を読み込む。ファイルが無ければ空リスト。
    """
    p = _path(ACTIVE_FILE)
    if not p.exists():
        return []
    result: list[Message] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                result.append({"role": rec.get("role", ""), "content": rec.get("content", "")})
            except json.JSONDecodeError:
                continue
    return result
