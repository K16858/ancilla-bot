"""
会話履歴の保存・読み込み
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Iterable

Message = dict[str, str]

DEFAULT_CONVERSATION_DIR = Path(os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation"))
ACTIVE_FILE = "active_history.jsonl"
OVERFLOW_FILE = "overflow.jsonl"


def is_system_event_content(content: str | None) -> bool:
    return (content or "").strip().startswith("[SYSTEM_EVENT")


def filter_system_event_messages(messages: Iterable[Message]) -> list[Message]:
    """
    [SYSTEM_EVENT ...] の user 発話と、直後の assistant 応答を除く。
    idle / heartbeat 等が長期記憶や要約を肥大化させないためのフィルタ。
    """
    items = list(messages)
    out: list[Message] = []
    i = 0
    while i < len(items):
        msg = items[i]
        if msg.get("role") == "user" and is_system_event_content(msg.get("content")):
            i += 1
            if i < len(items) and items[i].get("role") == "assistant":
                i += 1
            continue
        out.append(msg)
        i += 1
    return out


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _path(filename: str) -> Path:
    base = Path(os.getenv("ANCILLA_CONVERSATION_DIR", str(DEFAULT_CONVERSATION_DIR)))
    return base / filename


def _now_str() -> str:
    """
    タイムスタンプ文字列（YYYY-MM-DD HH:MM）を返す。
    """
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def append_overflow(messages: Iterable[Message]) -> None:
    """
    オーバーフローしたメッセージを overflow.jsonl に追記する。
    各行には role, content とあわせてタイムスタンプも保存する。
    SYSTEM_EVENT 由来の往復は保存しない。
    """
    msgs = filter_system_event_messages(messages)
    if not msgs:
        return
    p = _path(OVERFLOW_FILE)
    _ensure_dir(p.parent)
    with p.open("a", encoding="utf-8") as f:
        ts = _now_str()
        for m in msgs:
            record = {
                "role": m.get("role", ""),
                "content": m.get("content", ""),
                "ts": m.get("ts", ts),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_active_history(history: list[Message]) -> None:
    """
    アクティブな会話履歴を active_history.jsonl に保存する（上書き）。
    各行には role, content とあわせてタイムスタンプも保存する。
    既存メッセージに ts があればそれを優先し、無ければ現在時刻を付与する。
    """
    p = _path(ACTIVE_FILE)
    _ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as f:
        now_str = _now_str()
        for m in history:
            record = {
                "role": m.get("role", ""),
                "content": m.get("content", ""),
                "ts": m.get("ts", now_str),
            }
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
                msg: Message = {
                    "role": rec.get("role", ""),
                    "content": rec.get("content", ""),
                }
                ts = rec.get("ts")
                if isinstance(ts, str) and ts:
                    msg["ts"] = ts
                result.append(msg)
            except json.JSONDecodeError:
                continue
    return result


def load_overflow() -> list[Message]:
    """
    overflow.jsonl からオーバーフローしたメッセージを読み込む。ファイルが無ければ空リスト。
    時系列では active より古い（先に読むべき）側。
    """
    p = _path(OVERFLOW_FILE)
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
                msg: Message = {
                    "role": rec.get("role", ""),
                    "content": rec.get("content", ""),
                }
                ts = rec.get("ts")
                if isinstance(ts, str) and ts:
                    msg["ts"] = ts
                result.append(msg)
            except json.JSONDecodeError:
                continue
    return result
