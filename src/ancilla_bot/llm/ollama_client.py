"""
Ollamaエンドポイントへの簡易HTTPクライアント
"""

from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:4b"
DEFAULT_TIMEOUT = 60.0


def send_chat(
    messages: list[dict[str, str]],
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """
    OpenAI 互換の messages を送り、assistant の 1 件目の content を返す。

    Args:
        messages: [{"role": "user"|"assistant"|"system", "content": "..."}, ...]
        base_url: 例 "http://localhost:11434"
        model: 例 "qwen3:4b"
        timeout: リクエストタイムアウト（秒）

    Returns:
        LLM が返したテキスト（JSON 文字列想定）。エラー時は例外を投げる。
    """
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise ValueError("Ollama の応答に choices が含まれていません")
    content = choices[0].get("message", {}).get("content")
    if content is None:
        raise ValueError("Ollama の応答に message.content が含まれていません")
    return content.strip()
