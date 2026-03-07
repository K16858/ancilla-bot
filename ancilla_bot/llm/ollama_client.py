"""
Ollama 簡易 HTTP クライアント
"""

import json
import os
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DEFAULT_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
DEFAULT_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))


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
        "stream": False,
        "think": True,
    }
    if format is not None:
        body["format"] = format
    logger.debug("ollama request url={} model={} messages_count={}", url, model, len(messages))

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body)
            resp.raise_for_status()
    except httpx.ConnectError as e:
        logger.warning("ollama connect error: {}", e)
        raise
    except httpx.HTTPStatusError as e:
        logger.warning("ollama http error: {} {}", e.response.status_code, e.response.text[:200])
        raise
    except httpx.TimeoutException as e:
        logger.warning("ollama timeout: {}", e)
        raise

    try:
        data = resp.json()
    except json.JSONDecodeError:
        content_parts: list[str] = []
        for line in resp.text.strip().split("\n"):
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message") or {}
            part = msg.get("content")
            if part:
                content_parts.append(part)
        if not content_parts:
            raise ValueError("Ollama の応答に message.content が含まれていません")
        content = "".join(content_parts).strip()
        logger.debug("ollama response (ndjson) len={}", len(content))
        return content

    message = data.get("message")
    if not message:
        raise ValueError("Ollama の応答に message が含まれていません")
    content = message.get("content")
    if content is None:
        raise ValueError("Ollama の応答に message.content が含まれていません")
    logger.debug("ollama response len={}", len(content))
    return content.strip()


def embed_text(
    text: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_EMBED_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[float]:
    """
    Ollama /api/embed でテキストの埋め込みベクトルを取得する。

    Args:
        text: 埋め込み対象のテキスト
        base_url: 例 "http://localhost:11434"
        model: 例 "nomic-embed-text"
        timeout: リクエストタイムアウト（秒）

    Returns:
        埋め込みベクトル（float のリスト）。エラー時は例外を投げる。
    """
    url = f"{base_url.rstrip('/')}/api/embed"
    body: dict[str, Any] = {"model": model, "input": text}
    logger.debug("ollama embed url={} model={} text_len={}", url, model, len(text))

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()

    data = resp.json()
    embeddings = data.get("embeddings")
    if not embeddings:
        raise ValueError("Ollama embed の応答に embeddings が含まれていません")
    return [float(x) for x in embeddings[0]]
