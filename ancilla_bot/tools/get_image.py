"""
get_image
"""

from __future__ import annotations

import os
import queue
import uuid
from typing import Any


def _is_vision_enabled() -> bool:
    """
    メインモデルが視覚対応かどうか
    """
    raw = os.getenv("OLLAMA_VISION_ENABLED", "true")
    return (raw or "").strip().lower() in ("1", "true", "yes", "on")


def get_image(reason: str = "", timeout_sec: int = 60, **kwargs: Any) -> str:
    _ = kwargs
    from ancilla_bot.api.ws_server import (
        is_edge_session,
        register_camera_waiter,
        send_downlink,
        unregister_camera_waiter,
    )

    if not _is_vision_enabled():
        return (
            "メインモデルが視覚非対応として設定されています（OLLAMA_VISION_ENABLED が false）。"
            "画像を使った推論はできません。"
        )

    if not is_edge_session():
        return "エッジセッションではありません。先に use_edgedevice でエッジセッションに入ってください。"

    rid = str(uuid.uuid4())
    q = register_camera_waiter(rid)
    b64: str | None = None
    try:
        send_downlink(
            "media_request",
            {"kind": "camera", "request_id": rid, "reason": reason or ""},
        )
        b64 = q.get(timeout=max(5, int(timeout_sec)))
    except queue.Empty:
        pass
    finally:
        unregister_camera_waiter(rid)

    if not b64:
        return f"カメラ映像の取得がタイムアウトしました（{timeout_sec} 秒）。"

    return f"カメラ画像を取得しました（base64 長 {len(b64)}）。"

