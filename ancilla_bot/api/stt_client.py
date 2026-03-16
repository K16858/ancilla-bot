"""STT クライアント（faster-whisper-server / OpenAI 互換 API）"""

from __future__ import annotations
import os
import httpx


def _base_url() -> str:
    return (os.getenv("STT_BASE_URL") or "").rstrip("/")


def transcribe(audio_bytes: bytes, content_type: str = "audio/wav") -> str:
    """
    faster-whisper-server の POST /v1/audio/transcriptions で音声をテキスト化する。
    失敗時は空文字列を返す。
    """
    base = _base_url()
    if not base:
        return ""
    url = f"{base}/v1/audio/transcriptions"
    files = {"file": ("audio.wav", audio_bytes, content_type)}
    data = {"language": "ja"}
    try:
        r = httpx.post(url, files=files, data=data, timeout=60)
        r.raise_for_status()
        j = r.json()
        return (j.get("text") or "").strip()
    except (httpx.HTTPError, KeyError, ValueError):
        return ""
