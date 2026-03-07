"""
コンテキスト逼迫時に要約して圧縮
"""

from __future__ import annotations

import os
from typing import List

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
