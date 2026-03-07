from __future__ import annotations

import os
from typing import List

from ancilla_bot.llm import send_chat
from ancilla_bot.memory.short_term import Message, estimate_chars

TRIGGER_RATIO = float(os.getenv("ANCILLA_TIER2_TRIGGER_RATIO", "0.8"))
BLOCK_SIZE_MESSAGES = 10


def should_compress(history: List[Message], max_chars: int) -> bool:
    if max_chars <= 0:
        return False
    return estimate_chars(history) >= max_chars * TRIGGER_RATIO


def get_oldest_block(history: List[Message], block_size: int | None = None) -> List[Message]:
    n = block_size if block_size is not None else BLOCK_SIZE_MESSAGES
    n = max(1, min(n, len(history)))
    return list(history[:n])


def _block_text(messages: List[Message]) -> str:
    parts = []
    for m in messages:
        role = m.get("role", "")
        content = (m.get("content", "") or "").strip()
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def summarize_block(messages: List[Message]) -> str:
    text = _block_text(messages)
    if not text.strip():
        return ""
    prompt = "Summarize the following conversation in 1-3 sentences in Japanese. Output only the summary.\n\n" + text
    try:
        raw = send_chat([{"role": "user", "content": prompt}], format=None)
        summary = (raw or "").strip()
        return summary[:2000] if summary else ""
    except Exception:
        return text[:200] + ("..." if len(text) > 200 else "")
