"""LLM HTTP の共有クライアント。cancel / stop で in-flight を切断する。"""

from __future__ import annotations

import threading
from typing import Any

import httpx

_lock = threading.Lock()
_client: httpx.Client | None = None


def get_client() -> httpx.Client:
    global _client
    with _lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client()
        return _client


def close_client() -> None:
    global _client
    with _lock:
        if _client is not None:
            _client.close()
            _client = None


def post_json(url: str, body: dict[str, Any], *, timeout: float) -> httpx.Response:
    return get_client().post(url, json=body, timeout=timeout)
