from datetime import datetime, timedelta

import httpx
import pytest

from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import channel, status, store
from ancilla_bot.homelab import inventory as inv

YAML = """
hosts:
  - {id: host1, name: Host 1, os: ubuntu, node: true}
  - {id: plain, name: Plain, os: ubuntu}
services:
  - {id: web, name: Web, host: host1, kind: docker, unit: web, health_url: "http://web"}
  - {id: db, name: Db, host: host1, kind: systemd, unit: db}
  - {id: site, name: Site, host: host1, kind: http, health_url: "http://site"}
  - {id: ext, name: Ext, host: plain, kind: http, health_url: "http://ext"}
  - {id: unit, name: Unit, host: plain, kind: systemd, unit: x}
"""
NOW = datetime(2026, 11, 7, 12, 0, 0)
I = inv.parse_inventory(YAML)


def at(sec_ago: float) -> str:
    return (NOW - timedelta(seconds=sec_ago)).isoformat(timespec="seconds")


def node(web="running", db_="running", disk=50, mem=40, ago=0, extra=None):
    svcs = [{"id": "web", "state": web, "detail": ""}, {"id": "db", "state": db_, "detail": ""}]
    msg = {"resources": {"memory_percent": mem}, "disks": [{"mount": "/", "percent": disk}],
           "services": svcs if extra is None else extra}
    return {("host1", "node"): (msg, at(ago))}


def health(sid, ok, ago=0):
    return {(sid, "health"): ({"ok": ok}, at(ago))}


def ev(obs):
    return status.evaluate_all(NOW, 30, I, obs)


@pytest.mark.parametrize("web,hweb,expected", [
    ("running", True, "healthy"),
    ("running", False, "degraded"),
    ("stopped", True, "unhealthy"),
    ("failed", None, "unhealthy"),
])
def test_service_node_fresh(web, hweb, expected):
    obs = node(web=web)
    if hweb is not None:
        obs |= health("web", hweb)
    assert ev(obs)["web"].state == expected


def test_service_running_without_healthcheck_is_healthy():
    assert ev(node())["db"].state == "healthy"


def test_service_node_stale():
    assert ev(node(ago=100) | health("web", False))["web"].state == "unhealthy"
    assert ev(node(ago=100) | health("web", True))["web"].state == "healthy"
    assert ev(node(ago=100))["web"].state == "unknown"
    assert ev({})["web"].state == "unknown"
    # ヘルスチェックも stale
    assert ev(node(ago=100) | health("web", True, ago=100))["web"].state == "unknown"


def test_http_and_nodeless_services_judged_by_health():
    assert ev(health("site", True))["site"].state == "healthy"
    assert ev(health("site", False))["site"].state == "unhealthy"
    assert ev({})["site"].state == "unknown"
    assert ev(health("ext", False))["ext"].state == "unhealthy"
    r = ev({})["unit"]  # node: false の host 上の systemd: 観測不能
    assert r.state == "unknown" and r.mismatches


def test_mismatches():
    r = ev(node(extra=[{"id": "web", "state": "unknown", "detail": "unit not found"}]))
    assert "unit not found" in r["web"].mismatches[0]
    assert r["web"].state == "unknown"
    assert "報告していない" in r["db"].mismatches[0]


@pytest.mark.parametrize("disk,mem,expected", [
    (50, 40, "healthy"), (90, 40, "healthy"), (91, 40, "degraded"), (50, 96, "degraded"),
    (97, 40, "degraded"), (98, 40, "unhealthy"),
])
def test_host_thresholds(disk, mem, expected):
    assert ev(node(disk=disk, mem=mem))["host1"].state == expected


def test_host_node_lost_and_others():
    r = ev(node(ago=100) | health("site", True))["host1"]
    assert r.state == "degraded" and r.flags == ["node_lost"]
    r = ev(node(ago=100) | health("site", False) | health("web", False))["host1"]
    assert r.state == "unhealthy" and not r.flags
    assert ev(node(ago=100))["host1"].state == "unknown"
    assert ev({})["host1"].state == "unknown"
    assert ev(health("ext", True))["plain"].state == "healthy"  # node: false
    assert ev(health("ext", False))["plain"].state == "unhealthy"


def test_freshness_boundary():
    assert ev(node(ago=90))["host1"].state == "healthy"
    assert ev(node(ago=91))["host1"].state == "unknown"
    r = ev(node(ago=91))["host1"].evidence[0]
    assert r["freshness"] == "stale" and r["observed_at"] == at(91)
    assert ev({})["host1"].evidence[0]["freshness"] == "missing"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setattr(inv, "load_inventory", lambda: I)


def test_healthcheck_results(env):
    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host == "web":
            return httpx.Response(302)
        if host == "site":
            return httpx.Response(503)
        raise httpx.ConnectError("refused")

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        status.check_all(I, c)
    o = store.get_observations()
    assert o[("web", "health")][0]["ok"] is True
    assert o[("site", "health")][0] == {"ok": False, "status": 503, "error": ""}
    assert o[("ext", "health")][0]["ok"] is False and "ConnectError" in o[("ext", "health")][0]["error"]
    assert ("db", "health") not in o


def test_telemetry_handler_persists(env):
    channel.set_telemetry_handler(status.on_telemetry)
    channel._telemetry_handler("host1", {"type": "telemetry", "seq": 1})
    channel._telemetry_handler("host1", {"type": "telemetry", "seq": 2})
    channel.set_telemetry_handler(None)
    v, at_ = store.get_observations()[("host1", "node")]
    assert v["seq"] == 2 and at_  # 上書き


def test_tools(env):
    store.put_observation("host1", "node", {"seq": 1})
    assert '"host": "host1"' in status.homelab_get_metrics("host1")
    assert "Error" in status.homelab_get_metrics("nope")
    assert '"id": "host1"' in status.homelab_get_status()
    assert '"evidence"' in status.homelab_get_status("web")
    assert "Error" in status.homelab_get_status("nope")
