import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from ancilla_bot.heartbeat import db
from ancilla_bot.homelab import channel, store
from ancilla_bot.homelab import inventory as inv
from ancilla_bot.node import collect, daemon


@pytest.mark.parametrize(
    "out,expected",
    [
        ("ActiveState=active\nSubState=running\nLoadState=loaded\n", ("running", "active/running")),
        ("ActiveState=inactive\nSubState=dead\nLoadState=loaded\n", ("stopped", "inactive/dead")),
        ("ActiveState=failed\nSubState=failed\nLoadState=loaded\n", ("failed", "failed/failed")),
        ("ActiveState=inactive\nSubState=dead\nLoadState=not-found\n", ("unknown", "unit not found")),
        ("ActiveState=activating\nSubState=start\nLoadState=loaded\n", ("unknown", "activating/start")),
    ],
)
def test_parse_systemd(out, expected):
    assert collect.parse_systemd(out) == expected


def test_parse_docker():
    def js(status, code=0, health=None):
        st = {"Status": status, "ExitCode": code}
        if health:
            st["Health"] = {"Status": health}
        return '[{"State": %s}]' % __import__("json").dumps(st)

    assert collect.parse_docker(js("running"))[0] == "running"
    assert collect.parse_docker(js("running", health="unhealthy"))[0] == "failed"
    assert collect.parse_docker(js("exited", 0))[0] == "stopped"
    assert collect.parse_docker(js("exited", 137))[0] == "failed"
    assert collect.parse_docker("not json")[0] == "unknown"


def test_docker_unavailable_is_unknown(monkeypatch):
    def boom(cmd):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(collect, "_run", boom)
    assert collect.check_docker("web")[0] == "unknown"

    # 権限なし・コンテナなしは非 0 終了
    monkeypatch.setattr(
        collect, "_run", lambda cmd: subprocess.CompletedProcess(cmd, 1, "", "permission denied")
    )
    assert collect.check_docker("web") == ("unknown", "permission denied")


def test_unsupported_kind_is_unknown():
    assert collect.check_service({"id": "x", "kind": "windows_service", "unit": "W"})["state"] == "unknown"


def test_disk_filter(monkeypatch):
    parts = [
        SimpleNamespace(mountpoint="/", fstype="ext4"),
        SimpleNamespace(mountpoint="/run", fstype="tmpfs"),
        SimpleNamespace(mountpoint="/snap/x", fstype="squashfs"),
        SimpleNamespace(mountpoint="/var/lib/docker/overlay2/a", fstype="overlay"),
        SimpleNamespace(mountpoint="/mnt/data", fstype="xfs"),
    ]
    monkeypatch.setattr(collect.psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(collect.psutil, "disk_usage", lambda m: SimpleNamespace(percent=50.0))
    assert collect.collect_disks() == [
        {"mount": "/", "percent": 50.0},
        {"mount": "/mnt/data", "percent": 50.0},
    ]


def test_collect_shape():
    t = collect.collect(3, [{"id": "s", "kind": "http", "unit": None}])
    assert t["type"] == "telemetry" and t["seq"] == 3 and t["collected_at"]
    assert {"cpu_percent", "memory_percent", "swap_percent", "load_avg", "boot_time"} <= t["resources"].keys()
    assert t["services"] == [{"id": "s", "state": "unknown", "detail": "unsupported kind: http"}]


YAML = """
hosts:
  - {id: host1, name: Host 1, os: ubuntu, node: true}
services:
  - {id: web, name: Web, host: host1, kind: docker, unit: web}
"""


def test_daemon_sends_telemetry_and_reconnects(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setattr(inv, "load_inventory", lambda: inv.parse_inventory(YAML))
    monkeypatch.setattr(channel, "REPORT_INTERVAL_SEC", 0.2)
    monkeypatch.setattr(collect, "check_docker", lambda name: ("running", "running"))
    channel._connections.clear()
    channel.latest_telemetry.clear()
    got = []
    channel.set_telemetry_handler(lambda h, m: got.append(m))
    token = store.issue_token("host1")

    async def main():
        async with channel.make_server("127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            task = asyncio.create_task(
                daemon.run(f"ws://127.0.0.1:{port}", "host1", token, backoff_start=0.1, backoff_max=0.2)
            )
            await asyncio.sleep(1.0)
            assert got and got[0]["services"] == [{"id": "web", "state": "running", "detail": "running"}]
            n_before = len(got)
        # サーバー停止 -> 同じポートで再起動すると Node が再接続する
        await asyncio.sleep(0.3)
        async with channel.make_server("127.0.0.1", port):
            await asyncio.sleep(1.5)
        task.cancel()
        assert len(got) > n_before
        assert [m["seq"] for m in got] == sorted(m["seq"] for m in got)  # seq は接続をまたいで単調増加

    asyncio.run(main())
    channel.set_telemetry_handler(None)
