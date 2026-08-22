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
