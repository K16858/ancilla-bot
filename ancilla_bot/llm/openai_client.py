"""
OpenAI 互換 HTTP クライアント（llama.cpp server 等）
"""

import os
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "")
DEFAULT_EMBED_MODEL = os.getenv("LLM_EMBED_MODEL") or os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT") or os.getenv("OLLAMA_TIMEOUT", "60"))
VISION_ENABLED = os.getenv("OLLAMA_VISION_ENABLED", "true").strip().lower() in ("1", "true", "yes")
# think 未対応／不安定なモデル名の目印（既定 ON の例外）
_NON_THINKING_MODEL_MARKERS = ("granite", "llama", "mistral", "phi", "sarashina")


def _require_config(model: str | None) -> tuple[str, str]:
    base_url = DEFAULT_BASE_URL.strip()
    use_model = (model if model is not None else DEFAULT_MODEL).strip()
    if not base_url:
        raise ValueError("LLM_PROVIDER=openai のときは LLM_BASE_URL が必要です")
    if not use_model:
        raise ValueError("LLM_PROVIDER=openai のときは LLM_MODEL が必要です")
    return base_url.rstrip("/"), use_model


def _model_base_name(model: str) -> str:
    name = model.rsplit("/", 1)[-1].lower()
    return name.split(":", 1)[0]


def _should_think(model: str, *, format: dict[str, Any] | None) -> bool:
    """既定は ON。format 指定・OLLAMA_THINK・非対応モデル名で上書き。"""
    if format is not None:
        return False
    env = os.getenv("OLLAMA_THINK", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    base = _model_base_name(model)
    if any(marker in base for marker in _NON_THINKING_MODEL_MARKERS):
        return False
    return True


def _resolve_think(
    model: str,
    *,
    format: dict[str, Any] | None,
    think: bool | None,
) -> bool:
    if think is not None:
        return think
    return _should_think(model, format=format)


def _with_images(messages: list[dict[str, Any]], images: list[str]) -> list[dict[str, Any]]:
    messages = list(messages)
    if not messages or messages[-1].get("role") != "user":
        raise ValueError("画像付きリクエストには末尾の user メッセージが必要です")
    last = dict(messages[-1])
    text = last.get("content") or ""
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for img in images:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img}"},
            }
        )
    last["content"] = content
    return messages[:-1] + [last]


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Qwen / llama.cpp のチャットテンプレート制約に合わせる。
    すべての system を先頭 1 通にマージし、それ以外の順序はそのまま残す。
    """
    if not messages:
        return messages
    system_parts: list[str] = []
    rest: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "system":
            part = msg.get("content") or ""
            if part:
                system_parts.append(part if isinstance(part, str) else str(part))
            continue
        rest.append(msg)
    out: list[dict[str, Any]] = []
    if system_parts:
        out.append({"role": "system", "content": "\n\n".join(system_parts)})
    out.extend(rest)
    return out


def _extract_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if content is None:
        raise ValueError("OpenAI 互換応答に message.content が含まれていません")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    return str(content).strip()


def send_chat(
    messages: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    format: dict[str, Any] | None = None,
    images: list[str] | None = None,
    think: bool | None = None,
) -> str:
    """
    OpenAI 互換 /v1/chat/completions に messages を送り、assistant の content を返す。
    format 指定時は response_format=json_schema で出力を制約する。
    think: None ならモデル/OLLAMA_THINK から判定。明示指定で上書き。
    """
    resolved_base, use_model = _require_config(model)
    if base_url is not None:
        resolved_base = base_url.rstrip("/")
    if images and not VISION_ENABLED:
        raise ValueError("画像付きリクエストには OLLAMA_VISION_ENABLED=true が必要です")
    if images and VISION_ENABLED:
        messages = _with_images(messages, images)
    messages = _normalize_messages(messages)

    url = f"{resolved_base}/v1/chat/completions"
    body: dict[str, Any] = {
        "model": use_model,
        "messages": messages,
        "stream": False,
        "chat_template_kwargs": {
            "enable_thinking": _resolve_think(use_model, format=format, think=think)
        },
    }
    if format is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": format,
            },
        }
    max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip()
    if max_tokens:
        body["max_tokens"] = int(max_tokens)

    logger.debug("openai request url={} model={} messages_count={}", url, use_model, len(messages))
    data = _post_chat(url, body, timeout=timeout)
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenAI 互換応答に choices が含まれていません")
    message = choices[0].get("message") or {}
    content = _extract_content(message)
    logger.debug("openai response len={}", len(content))
    return content


def send_chat_message(
    messages: list[dict[str, Any]],
    *,
    base_url: str | None = None,
    model: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    format: dict[str, Any] | None = None,
    images: list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    think: bool | None = None,
) -> dict[str, Any]:
    """
    OpenAI 互換 /v1/chat/completions を呼び出し、message オブジェクトを返す。
    think: None ならモデル/OLLAMA_THINK から判定。明示指定で上書き。
    """
    resolved_base, use_model = _require_config(model)
    if base_url is not None:
        resolved_base = base_url.rstrip("/")
    if images and not VISION_ENABLED:
        raise ValueError("画像付きリクエストには OLLAMA_VISION_ENABLED=true が必要です")
    if images and VISION_ENABLED:
        messages = _with_images(messages, images)
    messages = _normalize_messages(messages)

    url = f"{resolved_base}/v1/chat/completions"
    body: dict[str, Any] = {
        "model": use_model,
        "messages": messages,
        "stream": False,
        "chat_template_kwargs": {
            "enable_thinking": _resolve_think(use_model, format=format, think=think)
        },
    }
    if format is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": format,
            },
        }
    if tools is not None:
        body["tools"] = tools
    max_tokens = os.getenv("LLM_MAX_TOKENS", "").strip()
    if max_tokens:
        body["max_tokens"] = int(max_tokens)

    logger.debug(
        "openai request url={} model={} messages_count={} tools={}",
        url,
        use_model,
        len(messages),
        len(tools or []),
    )
    data = _post_chat(url, body, timeout=timeout)
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("OpenAI 互換応答に choices が含まれていません")
    message = choices[0].get("message")
    if not message:
        raise ValueError("OpenAI 互換応答に message が含まれていません")
    return message


def _post_chat(url: str, body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        try:
            resp = client.post(url, json=body)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = (e.response.text or "")[:500]
            logger.warning(
                "openai http error status={} url={} body={}",
                e.response.status_code,
                url,
                detail,
            )
            raise
        except httpx.ConnectError as e:
            logger.warning("openai connect error: {}", e)
            raise
        except httpx.TimeoutException as e:
            logger.warning("openai timeout: {}", e)
            raise
        return resp.json()


def embed_text(
    text: str,
    *,
    base_url: str | None = None,
    model: str = DEFAULT_EMBED_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[float]:
    """
    OpenAI 互換 /v1/embeddings で埋め込みベクトルを取得する。
    """
    resolved_base = (base_url if base_url is not None else DEFAULT_BASE_URL).strip().rstrip("/")
    if not resolved_base:
        raise ValueError("LLM_PROVIDER=openai のときは LLM_BASE_URL が必要です")
    url = f"{resolved_base}/v1/embeddings"
    body: dict[str, Any] = {"model": model, "input": text}
    logger.debug("openai embed url={} model={} text_len={}", url, model, len(text))

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body)
        resp.raise_for_status()
        data = resp.json()

    items = data.get("data")
    if not items:
        raise ValueError("OpenAI 互換 embed の応答に data が含まれていません")
    embedding = items[0].get("embedding")
    if not embedding:
        raise ValueError("OpenAI 互換 embed の応答に embedding が含まれていません")
    return [float(x) for x in embedding]
