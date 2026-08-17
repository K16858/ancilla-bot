"""
mcp.json 設定の読み込み。

ANCILLA_MCP_CONFIG が無ければ mcp.json。無ければ空。
command → stdio、url → Streamable HTTP。両方ある行はスキップ。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

DEFAULT_CONFIG_PATH = Path(os.getenv("ANCILLA_MCP_CONFIG", "mcp.json"))


@dataclass(frozen=True)
class StdioServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


@dataclass(frozen=True)
class HttpServerConfig:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)


ServerConfig = StdioServerConfig | HttpServerConfig


def _as_str_dict(raw: Any, *, field_name: str, server: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        logger.warning("mcp server {!r}: {} must be an object; ignoring", server, field_name)
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        out[key] = "" if value is None else str(value)
    return out


def _parse_server(name: str, raw: Any) -> ServerConfig | None:
    if not isinstance(raw, dict):
        logger.warning("mcp server {!r}: expected object, got {}; skipping", name, type(raw).__name__)
        return None
    command = raw.get("command")
    url = raw.get("url")
    has_command = isinstance(command, str) and bool(command.strip())
    has_url = isinstance(url, str) and bool(url.strip())
    if has_command and has_url:
        logger.warning("mcp server {!r}: both command and url set; skipping", name)
        return None
    if has_command:
        args_raw = raw.get("args") or []
        if not isinstance(args_raw, list):
            logger.warning("mcp server {!r}: args must be a list; skipping", name)
            return None
        args = [str(a) for a in args_raw]
        cwd = raw.get("cwd")
        cwd_str = str(cwd).strip() if isinstance(cwd, str) and cwd.strip() else None
        return StdioServerConfig(
            name=name,
            command=command.strip(),
            args=args,
            env=_as_str_dict(raw.get("env"), field_name="env", server=name),
            cwd=cwd_str,
        )
    if has_url:
        return HttpServerConfig(
            name=name,
            url=url.strip(),
            headers=_as_str_dict(raw.get("headers"), field_name="headers", server=name),
        )
    logger.warning("mcp server {!r}: need command or url; skipping", name)
    return None


def load_mcp_config(path: Path | None = None) -> list[ServerConfig]:
    config_path = path if path is not None else Path(os.getenv("ANCILLA_MCP_CONFIG", str(DEFAULT_CONFIG_PATH)))
    if not config_path.is_file():
        return []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("mcp config {}: failed to load: {}", config_path, exc)
        return []
    if not isinstance(data, dict):
        logger.warning("mcp config {}: root must be an object", config_path)
        return []
    servers_raw = data.get("mcpServers")
    if servers_raw is None:
        return []
    if not isinstance(servers_raw, dict):
        logger.warning("mcp config {}: mcpServers must be an object", config_path)
        return []
    servers: list[ServerConfig] = []
    for name, raw in servers_raw.items():
        key = str(name).strip()
        if not key:
            continue
        parsed = _parse_server(key, raw)
        if parsed is not None:
            servers.append(parsed)
    return servers


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "mcp.json"
        assert load_mcp_config(p) == []
        p.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "local": {"command": "npx", "args": ["-y", "x"], "env": {"A": 1}},
                        "remote": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer t"}},
                        "bad": {"command": "a", "url": "http://x"},
                        "empty": {},
                    }
                }
            ),
            encoding="utf-8",
        )
        loaded = load_mcp_config(p)
        assert len(loaded) == 2, loaded
        assert isinstance(loaded[0], StdioServerConfig)
        assert loaded[0].name == "local"
        assert loaded[0].env == {"A": "1"}
        assert isinstance(loaded[1], HttpServerConfig)
        assert loaded[1].url == "https://example.com/mcp"
        print("ok")
