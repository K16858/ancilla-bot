"""STT クライアント（faster-whisper-server / OpenAI 互換 API）"""

from __future__ import annotations
import os
import httpx


_EXT_BY_CONTENT_TYPE = {
    "audio/webm": "audio.webm",
    "audio/ogg": "audio.ogg",
    "audio/mp4": "audio.m4a",
    "audio/m4a": "audio.m4a",
    "audio/x-m4a": "audio.m4a",
    "audio/mpeg": "audio.mp3",
    "audio/mp3": "audio.mp3",
}


def _base_url() -> str:
    return (os.getenv("STT_BASE_URL") or "").rstrip("/")


def is_configured() -> bool:
    """STT_BASE_URL が設定されているか返す。"""
    return bool(_base_url())


def transcribe(audio_bytes: bytes, content_type: str = "audio/wav", *, prompt: str = "") -> str:
    """
    faster-whisper-server の POST /v1/audio/transcriptions で音声をテキスト化する。
    失敗時は空文字列を返す。
    """
    base = _base_url()
    if not base:
        return ""
    base_ctype = (content_type or "audio/wav").split(";")[0].strip().lower() or "audio/wav"
    filename = _EXT_BY_CONTENT_TYPE.get(base_ctype, "audio.wav")
    url = f"{base}/v1/audio/transcriptions"
    files = {"file": (filename, audio_bytes, base_ctype)}
    data = {"language": "ja"}
    if prompt.strip():
        data["prompt"] = prompt.strip()
    try:
        r = httpx.post(url, files=files, data=data, timeout=60)
        r.raise_for_status()
        j = r.json()
        return (j.get("text") or "").strip()
    except (httpx.HTTPError, KeyError, ValueError):
        return ""
