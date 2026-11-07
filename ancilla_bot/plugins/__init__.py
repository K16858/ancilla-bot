"""同梱の任意プラグイン（stdio MCP サーバー）。ログは stderr のみ（stdout は MCP プロトコル用）。"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp_types import ToolAnnotations

MAX_CHARS = 6000
TIMEOUT = 15.0
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True)


def env_bool(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() not in ("0", "false", "no", "off")


def compact(data: Any, limit: int = MAX_CHARS) -> str:
    """LLM 向けに JSON を詰めて出力し、長ければ切り詰めて注記する。"""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n...[truncated: {len(text)} chars total, showing {limit}. narrow the query]"
