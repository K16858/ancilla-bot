from unittest import mock

import psutil
import pytest

from ancilla_bot.cli.commands import install
from ancilla_bot.node import collect


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(collect.sys, "platform", "win32")


@pytest.mark.parametrize("status,state", [
    ("running", "running"), ("stopped", "stopped"), ("paused", "stopped"),
    ("start_pending", "unknown"), ("stop_pending", "unknown"),
])
def test_status_mapping(win, monkeypatch, status, state):
    svc = mock.Mock()
    svc.as_dict.return_value = {"status": status}
    monkeypatch.setattr(psutil, "win_service_get", lambda n: svc, raising=False)
    assert collect.check_windows_service("Spooler") == (state, status)


def test_not_found(win, monkeypatch):
    def boom(n):
        raise psutil.NoSuchProcess(None, msg="x")
    monkeypatch.setattr(psutil, "win_service_get", boom, raising=False)
    assert collect.check_windows_service("nope") == ("unknown", "service not found")


def test_windows_disks_fixed_only(win, monkeypatch):
    from types import SimpleNamespace as NS
    parts = [NS(mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
             NS(mountpoint="D:\\", fstype="CDFS", opts="ro,cdrom"),
             NS(mountpoint="E:\\", fstype="FAT32", opts="rw,removable")]
    monkeypatch.setattr(collect.psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(collect.psutil, "disk_usage", lambda m: NS(percent=1.0))
    assert collect.collect_disks() == [{"mount": "C:\\", "percent": 1.0}]


def test_non_windows(monkeypatch):
    monkeypatch.setattr(collect.sys, "platform", "linux")
    assert collect.check_windows_service("x")[0] == "unknown"


def test_check_service_dispatch(monkeypatch):
    monkeypatch.setattr(collect, "check_windows_service", lambda n: ("running", "running"))
    r = collect.check_service({"id": "sp", "kind": "windows_service", "unit": "Spooler"})
    assert r == {"id": "sp", "state": "running", "detail": "running"}


def test_schtasks_cmd():
    assert install.schtasks_create_cmd("t.xml") == ["schtasks", "/Create", "/TN", "AncillaNode", "/XML", "t.xml", "/F"]


def test_task_xml():
    import xml.etree.ElementTree as ET
    x = install.task_xml(r"C:\a&b\ancilla.exe", r"PC\me", r"C:\root")
    ET.fromstring(x.split("?>", 1)[1])  # well-formed (escaped)
    for s in ["<ExecutionTimeLimit>PT0S<", "<DisallowStartIfOnBatteries>false<",
              "<StopIfGoingOnBatteries>false<", "IgnoreNew", "<Interval>PT1M<", "<Count>999<",
              "InteractiveToken", "LeastPrivilege", "<LogonTrigger>", r"C:\a&amp;b\ancilla.exe",
              "<Arguments>node<"]:
        assert s in x


def test_install_windows_runs_create_then_run(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(install.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(install.shutil, "which", lambda n: r"C:\x\ancilla.exe")
    assert install._install_node_windows(tmp_path) == 0
    assert calls[0][1] == "/Create" and "/XML" in calls[0] and calls[1][:2] == ["schtasks", "/Run"]
