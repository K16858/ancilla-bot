"""
会話ログの要約バッチ（Phase 1: 入力の結合とファイル出力）
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from ancilla_bot.memory.conversation_store import load_active_history, load_overflow

Message = dict[str, str]

DEFAULT_CONVERSATION_DIR = Path(os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation"))
SUMMARIES_DIR = "summaries"


def run_summarize() -> None:
    """
    overflow + active を時系列で結合し、summaries/YYYY-MM-DD.jsonl に書き出す。
    メッセージが 0 件の場合はファイルを作らない。
    """
    overflow = load_overflow()
    active = load_active_history()
    combined: list[Message] = overflow + active
    if not combined:
        return

    base = Path(os.getenv("ANCILLA_CONVERSATION_DIR", str(DEFAULT_CONVERSATION_DIR)))
    out_dir = base / SUMMARIES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = out_dir / f"{date_str}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for m in combined:
            record = {"role": m.get("role", ""), "content": m.get("content", "")}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
