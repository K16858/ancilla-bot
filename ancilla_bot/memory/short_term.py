"""
短期記憶（会話履歴）の管理ヘルパー
"""

from __future__ import annotations

from typing import Dict, List


Message = Dict[str, str]


def estimate_chars(messages: List[Message]) -> int:
    """
    非厳密なトークン見積もりとして、content の文字数合計を返す
    """
    return sum(len(m.get("content", "")) for m in messages)


def append_and_trim(
    history: List[Message],
    new_messages: List[Message],
    *,
    max_chars: int,
) -> List[Message]:
    """
    history に new_messages を追加し、max_chars を超えたぶんだけ
    先頭から古いメッセージを削って返す

    戻り値: 削除された（オーバーフローした）メッセージのリスト
    """
    history.extend(new_messages)
    dropped: List[Message] = []

    while history and estimate_chars(history) > max_chars:
        dropped.append(history.pop(0))

    return dropped

