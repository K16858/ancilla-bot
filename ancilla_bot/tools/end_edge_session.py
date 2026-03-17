"""
end_edge_session ツール
"""

from __future__ import annotations

from typing import Any


def end_edge_session(**kwargs: Any) -> str:
    """エッジセッションを終了してメインに戻す。エッジセッションでない場合はその旨を返す。"""
    _ = kwargs
    from ancilla_bot.api.ws_server import _end_edge_session, is_edge_session

    if not is_edge_session():
        return "現在、エッジセッションは開始されていません。"

    _end_edge_session()
    return "エッジセッションを終了し、メインセッションに戻りました。"
