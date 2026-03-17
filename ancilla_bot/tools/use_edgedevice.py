"""
use_edgedevice ツール: エッジセッションへ切り替える。
クライアントがマイク／カメラ入力を送れるようにするトリガー。
"""

from __future__ import annotations

from typing import Any


def use_edgedevice(target: str = "", reason: str = "", **kwargs: Any) -> str:
    """
    エッジセッションに切り替える。main のときは切り替え＋show_avatar を送信。
    action_input: {"target": "optional", "reason": "optional"}
    """
    _ = kwargs
    from ancilla_bot.api.ws_server import switch_to_edge_session_if_needed

    switched = switch_to_edge_session_if_needed()
    if switched:
        return "エッジセッションに切り替えました。マイクやカメラからの入力が利用可能です。"
    return "すでにエッジセッションです。マイクやカメラからの入力を利用できます。"
