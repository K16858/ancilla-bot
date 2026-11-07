import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import channel, store
from ancilla_bot.homelab import inventory as inv

YAML = """
hosts:
  - {id: host1, name: Host 1, os: ubuntu, node: true}
  - {id: host2, name: Host 2, os: ubuntu, node: true}
  - {id: plain, name: Plain, os: ubuntu}
services:
  - {id: web, name: Web, host: host1, kind: docker, unit: web}
  - {id: site, name: Site, host: host1, kind: http, health_url: "http://x"}
"""


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setattr(inv, "load_inventory", lambda: inv.parse_inventory(YAML))
    channel._connections.clear()
    channel.latest_telemetry.clear()
    channel.set_telemetry_handler(None)


def run(coro_fn):
    async def main():
        async with channel.make_server("127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            await coro_fn(f"ws://127.0.0.1:{port}")

    asyncio.run(main())


def hello(host="host1"):
    return json.dumps({"type": "hello", "host_id": host, "version": "1.0", "os": "linux", "hostname": "h"})


def conn(url, token):
    return connect(url, additional_headers={"Authorization": f"Bearer {token}"})


def test_valid_token_gets_config_and_telemetry():
    token = store.issue_token("host1")
    got = []
    channel.set_telemetry_handler(lambda h, m: got.append((h, m["seq"])))

    async def body(url):
        async with conn(url, token) as ws:
            await ws.send(hello())
            cfg = json.loads(await ws.recv())
            assert cfg == {
                "type": "config",
                "interval": 30,
                "services": [{"id": "web", "kind": "docker", "unit": "web"}],
            }
            await ws.send(json.dumps({"type": "telemetry", "seq": 1}))
            await asyncio.sleep(0.2)

    run(body)
    assert got == [("host1", 1)] and channel.latest_telemetry["host1"]["seq"] == 1
    n = store.list_nodes()[0]
    assert n["os"] == "linux" and n["version"] == "1.0" and n["last_seen"]


def test_token_is_stored_hashed():
    token = store.issue_token("host1")
    with store._conn() as c:
        assert c.execute("SELECT token_hash FROM nodes").fetchone()[0] != token


@pytest.mark.parametrize("kind", ["unknown", "revoked", "reissued", "none"])
def test_bad_token_rejected(kind):
    token = store.issue_token("host1")
    if kind == "revoked":
        store.revoke("host1")
    elif kind == "reissued":
        store.issue_token("host1")
    elif kind == "unknown":
        token = "nope"

    async def body(url):
        headers = {} if kind == "none" else {"Authorization": f"Bearer {token}"}
        with pytest.raises(InvalidStatus) as e:
            async with connect(url, additional_headers=headers):
                pass
        assert e.value.response.status_code == 401

    run(body)


def test_other_host_hello_rejected():
    token = store.issue_token("host1")
    store.issue_token("host2")

    async def body(url):
        async with conn(url, token) as ws:
            await ws.send(hello("host2"))
            with pytest.raises(ConnectionClosed):
                await ws.recv()

    run(body)


def test_duplicate_connection_closes_old():
    token = store.issue_token("host1")

    async def body(url):
        async with conn(url, token) as old:
            await old.send(hello())
            await old.recv()
            async with conn(url, token) as new:
                await new.send(hello())
                await new.recv()
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(old.recv(), 2)
                assert channel.is_connected("host1")

    run(body)


def test_revoke_disconnects(monkeypatch):
    monkeypatch.setattr(channel, "RECHECK_SEC", 0.1)
    token = store.issue_token("host1")

    async def body(url):
        async with conn(url, token) as ws:
            await ws.send(hello())
            await ws.recv()
            store.revoke("host1")
            with pytest.raises(ConnectionClosed):
                await asyncio.wait_for(ws.recv(), 2)

    run(body)
