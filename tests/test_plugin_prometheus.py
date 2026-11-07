from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ancilla_bot.plugins import prometheus as prom


def _mock(monkeypatch, handler, token=None):
    monkeypatch.setenv("PROMETHEUS_URL", "http://prom.test:9090")
    if token:
        monkeypatch.setenv("PROMETHEUS_TOKEN", token)
    else:
        monkeypatch.delenv("PROMETHEUS_TOKEN", raising=False)
    monkeypatch.setattr(prom, "_TRANSPORT", httpx.MockTransport(handler))


def _ok(data):
    return httpx.Response(200, json={"status": "success", "data": data})


def test_query_and_token_header(monkeypatch):
    seen = {}

    def h(req):
        seen["auth"] = req.headers.get("authorization")
        seen["q"] = req.url.params["query"]
        return _ok({"resultType": "vector", "result": [{"metric": {"instance": "a:9100"}, "value": [1, "1"]}]})

    _mock(monkeypatch, h, token="tok")
    out = json.loads(prom.query("up"))
    assert seen == {"auth": "Bearer tok", "q": "up"}
    assert out["count"] == 1 and out["series"][0]["value"] == [1, "1"]


def test_no_token_no_header(monkeypatch):
    seen = {}

    def h(req):
        seen["auth"] = req.headers.get("authorization")
        return _ok({"resultType": "vector", "result": []})

    _mock(monkeypatch, h)
    prom.query("up")
    assert seen["auth"] is None


def test_query_range(monkeypatch):
    def h(req):
        assert req.url.path == "/api/v1/query_range"
        assert req.url.params["step"] == "30s"
        return _ok({"resultType": "matrix", "result": [{"metric": {}, "values": [[1, "1"], [2, "2"]]}]})

    _mock(monkeypatch, h)
    out = json.loads(prom.query_range("up", "1", "2", "30s"))
    assert out["series"][0]["values"] == [[1, "1"], [2, "2"]]


def test_alerts(monkeypatch):
    alert = {
        "labels": {"alertname": "HighCPU", "instance": "a"},
        "state": "firing",
        "annotations": {"summary": "cpu high"},
        "activeAt": "t",
    }
    _mock(monkeypatch, lambda r: _ok({"alerts": [alert]}))
    out = json.loads(prom.alerts())
    assert out["alerts"][0]["name"] == "HighCPU" and out["alerts"][0]["summary"] == "cpu high"


def test_targets_unhealthy_first(monkeypatch):
    t = lambda inst, h, err="": {"labels": {"job": "node", "instance": inst}, "health": h, "lastError": err}  # noqa: E731
    _mock(monkeypatch, lambda r: _ok({"activeTargets": [t("a", "up"), t("b", "down", "refused")]}))
    out = json.loads(prom.targets())
    assert out["down"] == 1 and out["targets"][0]["instance"] == "b"
    assert out["targets"][0]["lastError"] == "refused"


def test_truncation(monkeypatch):
    rows = [{"metric": {"i": str(i)}, "value": [1, "1"]} for i in range(2000)]
    _mock(monkeypatch, lambda r: _ok({"resultType": "vector", "result": rows}))
    assert "truncated" in prom.query("x")


def test_errors(monkeypatch):
    _mock(monkeypatch, lambda r: httpx.Response(400, json={"status": "error", "error": "bad"}))
    with pytest.raises(RuntimeError, match="HTTP 400"):
        prom.query("x")
    _mock(monkeypatch, lambda r: httpx.Response(200, json={"status": "error", "errorType": "bad_data", "error": "parse"}))
    with pytest.raises(RuntimeError, match="bad_data"):
        prom.query("x")

    def boom(req):
        raise httpx.ConnectError("nope")

    _mock(monkeypatch, boom)
    with pytest.raises(RuntimeError, match="request failed"):
        prom.query("x")
    monkeypatch.delenv("PROMETHEUS_URL")
    with pytest.raises(ValueError):
        prom.query("x")


def test_tools_are_read_only_annotated():
    tools = asyncio.run(prom.create_server().list_tools())
    assert sorted(t.name for t in tools) == ["alerts", "query", "query_range", "targets"]
    assert all(t.annotations.read_only_hint is True for t in tools)
    from ancilla_bot.mcp.bridge import _effect_from_annotations
    from ancilla_bot.runtime import policy

    assert all(_effect_from_annotations(t) == "external_read" for t in tools)
    # 承認なし・自律実行でも拒否されない
    assert "external_read" not in policy._AUTONOMOUS_DENY | policy._REQUIRE_APPROVAL
