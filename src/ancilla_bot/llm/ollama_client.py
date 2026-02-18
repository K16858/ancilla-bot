"""
Ollama 簡易 HTTP クライアント
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
    format: dict[str, Any] | None = None,
) -> str:
    """
    Ollama ネイティブ API に messages を送り、assistant の content を返す。

    Args:
        messages: [{"role": "user"|"assistant"|"system", "content": "..."}, ...]
        base_url: 例 "http://localhost:11434"
        model: 例 "qwen3:4b"
        timeout: リクエストタイムアウト（秒）
        format: 省略時は自由出力。指定時は JSON Schema（例: Pydantic の model_json_schema()）
                を渡し、Ollama が GBNF で出力を制約する。

    Returns:
        LLM が返したテキスト。format 指定時は JSON 文字列。エラー時は例外を投げる。
    """
    url = f"{base_url.rstrip('/')}/api/chat"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if format is not None:
        body["format"] = format

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    message = data.get("message")
    if not message:
        raise ValueError("Ollama の応答に message が含まれていません")
    content = message.get("content")
    if content is None:
        raise ValueError("Ollama の応答に message.content が含まれていません")
    return content.strip()
