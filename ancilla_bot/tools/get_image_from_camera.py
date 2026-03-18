"""
get_image_from_camera ツール
"""

from __future__ import annotations

from typing import Any


def get_image_from_camera(reason: str = "", **kwargs: Any) -> str:
    """
    エッジセッション中に、最新の vision_input 画像についての情報を取得する。
    現時点では画像そのものではなく、状態説明のみを返す。
    """
    _ = kwargs
    from ancilla_bot.api.ws_server import get_latest_vision_image, is_edge_session

    if not is_edge_session():
        return "現在はエッジセッションではありません。まず use_edgedevice ツールでエッジセッションに切り替えてください。"

    image_b64 = get_latest_vision_image()
    if not image_b64:
        return "まだカメラ画像（vision_input）が受信されていません。デバイス側でカメラを有効にしてください。"

    # TODO
    return f"最新のカメラ画像が利用可能です（base64 長さ={len(image_b64)}）"

