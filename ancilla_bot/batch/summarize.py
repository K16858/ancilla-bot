"""
会話ログの要約バッチ
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from loguru import logger

from ancilla_bot.llm import send_chat
from ancilla_bot.memory.conversation_store import load_active_history, load_overflow

Message = dict[str, str]

DEFAULT_CONVERSATION_DIR = Path(os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation"))
SUMMARIES_DIR = "summaries"
TURNS_PER_BLOCK = 5
SUMMARY_PROMPT = """Summarize the following conversation block in 1-3 sentences in Japanese. Output only the summary, no other text.

Conversation:
"""
OBSERVATION_MARKER = "Observation:"


def _block_text(messages: list[Message]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "")
        content = (m.get("content", "") or "").strip()
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _tool_used_in_block(messages: list[Message]) -> bool:
    return any(OBSERVATION_MARKER in (m.get("content") or "") for m in messages)


def _summarize_block(block_messages: list[Message]) -> str:
    text = _block_text(block_messages)
    if not text.strip():
        return "（内容なし）"
    prompt = SUMMARY_PROMPT + text
    messages = [{"role": "user", "content": prompt}]
    try:
        raw = send_chat(messages, format=None)
        summary = (raw or "").strip()
        return summary[:2000] if summary else "（要約なし）"
    except Exception as e:
        logger.warning("summarize LLM error: {} -> fallback", e)
        return (text[:150] + "..." if len(text) > 150 else text) or "（要約エラー）"


def run_summarize() -> None:
    """
    overflow + active を時系列で結合し、N 往復ごとにブロック分割
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

    block_size = 2 * TURNS_PER_BLOCK
    records = []

    for start in range(0, len(combined), block_size):
        end_index = min(start + block_size, len(combined)) - 1
        block = combined[start : end_index + 1]
        summary = _summarize_block(block)
        tool_used = _tool_used_in_block(block)
        record = {
            "date": date_str,
            "start_index": start,
            "end_index": end_index,
            "summary": summary,
            "message_count": len(block),
            "tool_used": tool_used,
        }
        records.append(record)

    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info("batch summarize wrote {} blocks to {}", len(records), out_path)
