"""Core health チェックと待機。"""

from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import httpx


def core_url() -> str:
    """Client/Adapter が接続する Core URL。"""
    raw = (os.getenv("ANCILLA_CORE_URL") or "").strip()
    if raw:
        return raw.rstrip("/")
    host = os.getenv("ANCILLA_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.getenv("ANCILLA_API_PORT", "8765"))
    return f"http://{host}:{port}"


def api_bind_host() -> str:
    """Core が listen するホスト。"""
    bind = (os.getenv("ANCILLA_API_BIND_HOST") or "").strip()
    if bind:
        return bind
    return os.getenv("ANCILLA_API_HOST", "127.0.0.1").strip() or "127.0.0.1"


def api_bind_port() -> int:
    return int(os.getenv("ANCILLA_API_PORT", "8765"))


def health_url(base: str | None = None) -> str:
    return f"{(base or core_url()).rstrip('/')}/health"


def check_health(base: str | None = None, *, timeout: float = 2.0) -> bool:
    url = health_url(base)
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            return resp.status_code == 200
    except Exception:
        return False


def wait_healthy(
    base: str | None = None,
    *,
    timeout_sec: float = 30.0,
    interval_sec: float = 0.5,
) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if check_health(base):
            return True
        time.sleep(interval_sec)
    return False


def display_endpoint(base: str | None = None) -> str:
    return (base or core_url()).rstrip("/")


def host_port_from_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def ollama_models(base_url: str | None = None, *, timeout: float = 3.0) -> list[str] | None:
    """Ollama の /api/tags のモデル名一覧。到達不能なら None、0 件なら空リスト。"""
    base = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{base}/api/tags")
            if resp.status_code != 200:
                return None
            return [m.get("name", "") for m in (resp.json().get("models") or [])]
    except Exception:
        return None


def ollama_has_model(models: list[str], model: str) -> bool:
    """タグ省略（llama3 で llama3:8b にマッチ）を許容した存在判定。"""
    stem = model.split(":")[0]
    return any(n == model or n.startswith(f"{stem}:") for n in models)
