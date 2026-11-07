from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ancilla_bot.plugins import wazuh


def _env(monkeypatch, handler):
    for k, v in {
        "WAZUH_INDEXER_URL": "https://idx.test:9200",
        "WAZUH_INDEXER_USER": "iu",
        "WAZUH_INDEXER_PASSWORD": "ip",
        "WAZUH_API_URL": "https://api.test:55000",
        "WAZUH_API_USER": "au",
        "WAZUH_API_PASSWORD": "ap",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(wazuh, "_TRANSPORT", httpx.MockTransport(handler))


def test_list_agents_auth_flow(monkeypatch):
    calls = []

    def h(req):
        calls.append((req.url.path, req.headers.get("authorization")))
        if req.url.path == "/security/user/authenticate":
            return httpx.Response(200, text="JWT123")
        return httpx.Response(
            200,
            json={
                "data": {
                    "total_affected_items": 2,
                    "affected_items": [
                        {"id": "001", "name": "host1", "ip": "1.1.1.1", "status": "active", "os": {"name": "Debian"}},
                        {"id": "002", "name": "host2", "status": "disconnected"},
                    ],
                }
            },
        )

    _env(monkeypatch, h)
    out = json.loads(wazuh.list_agents())
    assert calls[0][1].startswith("Basic ")
    assert calls[1] == ("/agents", "Bearer JWT123")
    assert out["total"] == 2 and out["agents"][0]["name"] == "host2"  # 異常を先頭に


def test_search_alerts(monkeypatch):
    seen = {}

    def h(req):
        seen["path"] = req.url.path
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "hits": {
                    "total": {"value": 5},
                    "hits": [
                        {
                            "_source": {
                                "@timestamp": "t",
                                "agent": {"name": "host1"},
                                "rule": {"level": 10, "id": "5712", "description": "sshd brute force"},
                                "full_log": "x" * 1000,
                            }
                        }
                    ],
                }
            },
        )

    _env(monkeypatch, h)
    out = json.loads(wazuh.search_alerts(query="rule.id:5712", min_level=7, agent="host1", limit=999))
    assert seen["path"] == "/wazuh-alerts-*/_search" and seen["auth"].startswith("Basic ")
    assert seen["body"]["size"] == 50
    assert out["total"] == 5 and out["alerts"][0]["desc"] == "sshd brute force"
    assert len(out["alerts"][0]["log"]) == 300


def test_errors(monkeypatch):
    _env(monkeypatch, lambda r: httpx.Response(401, text="denied"))
    with pytest.raises(RuntimeError, match="HTTP 401"):
        wazuh.list_agents()
    monkeypatch.delenv("WAZUH_INDEXER_URL")
    with pytest.raises(ValueError):
        wazuh.search_alerts()


def test_tools_read_only():
    tools = asyncio.run(wazuh.create_server().list_tools())
    assert sorted(t.name for t in tools) == ["list_agents", "search_alerts"]
    assert all(t.annotations.read_only_hint is True for t in tools)
