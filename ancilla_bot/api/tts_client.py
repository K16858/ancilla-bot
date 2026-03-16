"""TTS クライアント（Coeiroink）"""

from __future__ import annotations

import os

import httpx

# Coeiroink デフォルト話者
DEFAULT_SPEAKER_UUID = "3c37646f-3881-5374-2a83-149267990abc"
DEFAULT_STYLE_ID = 0


def _base_url() -> str:
    return (os.getenv("TTS_BASE_URL") or "").rstrip("/")


def synthesize(text: str) -> bytes:
    """
    Coeiroink の POST /v1/synthesis でテキストを音声化する。
    TTS_BASE_URL 未設定または失敗時は空 bytes を返す。
    """
    base = _base_url()
    if not base or not text.strip():
        return b""
    url = f"{base}/v1/synthesis"
    body = {
        "text": text,
        "speakerUuid": os.getenv("TTS_SPEAKER_UUID", DEFAULT_SPEAKER_UUID),
        "styleId": int(os.getenv("TTS_STYLE_ID", str(DEFAULT_STYLE_ID))),
        "speedScale": 1,
        "volumeScale": 1,
        "pitchScale": 0,
        "intonationScale": 1,
        "prePhonemeLength": 0,
        "postPhonemeLength": 0,
        "outputSamplingRate": 44100,
        "processingAlgorithm": "coeiroink",
    }
    try:
        r = httpx.post(
            url,
            json=body,
            headers={"Accept": "audio/wav", "Content-Type": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        return r.content
    except httpx.HTTPError:
        return b""
