import json
from pathlib import Path

from ancilla_bot.mcp.config import HttpServerConfig, StdioServerConfig, load_mcp_config


def test_missing_file_returns_empty(tmp_path: Path):
    assert load_mcp_config(tmp_path / "mcp.json") == []


def test_load_stdio_and_http_skips_both(tmp_path: Path):
    p = tmp_path / "mcp.json"
    p.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local": {"command": "npx", "args": ["-y", "x"], "env": {"A": 1}},
                    "remote": {
                        "url": "https://example.com/mcp",
                        "headers": {"Authorization": "Bearer t"},
                    },
                    "bad": {"command": "a", "url": "http://x"},
                    "empty": {},
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = load_mcp_config(p)
    assert len(loaded) == 2
    assert isinstance(loaded[0], StdioServerConfig)
    assert loaded[0].name == "local"
    assert loaded[0].env == {"A": "1"}
    assert isinstance(loaded[1], HttpServerConfig)
    assert loaded[1].url == "https://example.com/mcp"
