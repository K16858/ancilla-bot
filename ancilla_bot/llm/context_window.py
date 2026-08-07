"""
LLM のコンテキスト長取得と履歴上限の自動算出
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

_DEFAULT_HISTORY_CHARS = 4000
_CHARS_PER_TOKEN = float(os.getenv("ANCILLA_CHARS_PER_TOKEN", "2.0"))


def fetch_n_ctx() -> int | None:
    """
    接続先から実行中コンテキスト長（トークン）を取得する。
    取得失敗時は None。
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    try:
        if provider == "openai":
            return _fetch_n_ctx_openai()
        return _fetch_n_ctx_ollama()
    except Exception as e:
        logger.warning("fetch_n_ctx failed: {}", e)
        return None


def _fetch_n_ctx_openai() -> int | None:
    base = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return None
    timeout = float(os.getenv("LLM_TIMEOUT") or os.getenv("OLLAMA_TIMEOUT", "10"))
    with httpx.Client(timeout=min(timeout, 15.0)) as client:
        try:
            resp = client.get(f"{base}/props")
            if resp.status_code == 200:
                data = resp.json()
                n_ctx = (data.get("default_generation_settings") or {}).get("n_ctx")
                if isinstance(n_ctx, int) and n_ctx > 0:
                    return n_ctx
        except Exception:
            pass
        resp = client.get(f"{base}/v1/models")
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data") or []
        if not models:
            return None
        meta = models[0].get("meta") or {}
        n_ctx = meta.get("n_ctx")
        if isinstance(n_ctx, int) and n_ctx > 0:
            return n_ctx
    return None


def _fetch_n_ctx_ollama() -> int | None:
    base = (os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").strip().rstrip("/")
    model = (os.getenv("OLLAMA_MODEL") or "").strip()
    if not model:
        return None
    timeout = float(os.getenv("OLLAMA_TIMEOUT", "10"))
    with httpx.Client(timeout=min(timeout, 15.0)) as client:
        resp = client.post(f"{base}/api/show", json={"name": model})
        resp.raise_for_status()
        data = resp.json()
    info: dict[str, Any] = data.get("model_info") or {}
    for key, value in info.items():
        if str(key).endswith(".context_length"):
            n = int(value)
            if n > 0:
                return n
    return None


def history_chars_from_n_ctx(n_ctx: int) -> int:
    """
    n_ctx の半分を短期履歴予算とし、文字数に換算する。
    残り半分は system / tools / 生成用の余裕。
    """
    if n_ctx <= 0:
        return _DEFAULT_HISTORY_CHARS
    chars_per_token = _CHARS_PER_TOKEN if _CHARS_PER_TOKEN > 0 else 2.0
    budget_tokens = max(256, n_ctx // 2)
    return max(1000, int(budget_tokens * chars_per_token))


def resolve_max_history_chars() -> int:
    """
    ANCILLA_MAX_HISTORY_CHARS が明示されていればそれを使う。
    未設定なら API から n_ctx を取り自動算出。失敗時は 4000。
    """
    explicit = os.getenv("ANCILLA_MAX_HISTORY_CHARS", "").strip()
    if explicit:
        value = int(explicit)
        logger.info("max_history_chars={} (ANCILLA_MAX_HISTORY_CHARS)", value)
        return value
    n_ctx = fetch_n_ctx()
    if n_ctx is None:
        logger.info(
            "max_history_chars={} (default; n_ctx unavailable)",
            _DEFAULT_HISTORY_CHARS,
        )
        return _DEFAULT_HISTORY_CHARS
    value = history_chars_from_n_ctx(n_ctx)
    logger.info("max_history_chars={} (auto from n_ctx={})", value, n_ctx)
    return value
