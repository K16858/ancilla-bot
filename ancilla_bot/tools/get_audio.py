"""
get_audio
"""

from __future__ import annotations

import queue
import uuid
from typing import Any


def get_audio(reason: str = "", timeout_sec: int = 60, **kwargs: Any) -> str:
    _ = kwargs
    from ancilla_bot.api.ws_server import (
        is_edge_session,
        register_mic_waiter,
        send_downlink,
        unregister_mic_waiter,
    )

    if not is_edge_session():
        return "エッジセッションではありません。先に use_edgedevice でエッジセッションに入ってください。"

    rid = str(uuid.uuid4())
    q = register_mic_waiter(rid)
    text: str | None = None
    try:
        send_downlink(
            "media_request",
            {"kind": "microphone", "request_id": rid, "reason": reason or ""},
        )
        text = q.get(timeout=max(5, int(timeout_sec)))
    except queue.Empty:
        pass
    finally:
        unregister_mic_waiter(rid)

    if text is None:
        return (
            f"マイク取得がタイムアウトしました（{timeout_sec} 秒）。"
        )

    return f"[マイク取得·STT] {text}"
