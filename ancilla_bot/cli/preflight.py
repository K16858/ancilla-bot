"""起動前の LLM endpoint / モデル確認。失敗時は heartbeat を回さない。"""

from __future__ import annotations

import os

from loguru import logger


def run_preflight() -> str | None:
    """問題があれば理由文字列。問題なければ None。"""
    provider = (os.getenv("LLM_PROVIDER") or "ollama").strip().lower()
    if provider == "openai":
        base = (os.getenv("LLM_BASE_URL") or "").strip()
        model = (os.getenv("LLM_MODEL") or "").strip()
        if not base or not model:
            return "LLM_BASE_URL and LLM_MODEL are required for openai."
        return _probe_inference()
    from ancilla_bot.cli import health

    base = (os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    models = health.ollama_models(base)
    if models is None:
        return f"LLM endpoint unreachable: {base}"
    model = (os.getenv("OLLAMA_MODEL") or "").strip()
    if not model:
        return "OLLAMA_MODEL is not set."
    if not health.ollama_has_model(models, model):
        return f"Ollama model not found: {model}"
    return _probe_inference()


def _probe_inference() -> str | None:
    from ancilla_bot.llm import send_chat

    try:
        raw = send_chat([{"role": "user", "content": "ping"}], think=False)
    except Exception as e:
        return f"LLM inference failed: {e}"
    if not (raw or "").strip():
        return "LLM inference returned empty output."
    logger.info("preflight inference ok")
    return None
