"""Node が集める情報（psutil / systemd / docker）。

telemetry メッセージの形（PR 08 はこれを読む）::

    {
      "type": "telemetry",
      "seq": 12,                          # 接続をまたいで単調増加
      "collected_at": "2026-11-07T01:02:03+00:00",   # UTC ISO 8601
      "resources": {
        "cpu_percent": 3.2,               # 前回収集からの平均
        "memory_percent": 41.0,
        "swap_percent": 0.0,
        "load_avg": [0.1, 0.2, 0.3],      # 1/5/15 分。取得できない OS（Windows）では null
        "boot_time": 1730000000.0         # epoch 秒
      },
      "disks": [{"mount": "/", "percent": 55.1}],     # 実ファイルシステムのみ
      "services": [                       # config で受け取った対象ごと 1 件
        {"id": "web", "state": "running|stopped|failed|unknown", "detail": "active/running"}
      ]
    }

state が取れない（docker 不在・権限なし・未対応 kind など）ときは "unknown" とし、理由を detail に入れる。
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

import psutil

# 実ファイルシステムではないもの
_PSEUDO_FS = {
    "tmpfs", "devtmpfs", "squashfs", "overlay", "proc", "sysfs", "cgroup", "cgroup2",
    "devpts", "securityfs", "pstore", "bpf", "tracefs", "debugfs", "configfs", "fusectl",
    "mqueue", "hugetlbfs", "autofs", "binfmt_misc", "nsfs", "ramfs", "efivarfs", "fuse.lxcfs",
}
_CMD_TIMEOUT = 5


def is_real_fs(fstype: str) -> bool:
    return bool(fstype) and fstype.lower() not in _PSEUDO_FS


def collect_disks() -> list[dict]:
    out = []
    for p in psutil.disk_partitions(all=False):
        if not is_real_fs(p.fstype):
            continue
        try:
            out.append({"mount": p.mountpoint, "percent": psutil.disk_usage(p.mountpoint).percent})
        except OSError:
            continue  # cdrom 空き・権限なし等
    return out


def collect_resources() -> dict:
    try:
        load = list(psutil.getloadavg())
    except (AttributeError, OSError):
        load = None
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "swap_percent": psutil.swap_memory().percent,
        "load_avg": load,
        "boot_time": psutil.boot_time(),
    }


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_CMD_TIMEOUT)


def parse_systemd(output: str) -> tuple[str, str]:
    """`systemctl show -p ActiveState,SubState,LoadState` の出力 -> (state, detail)。"""
    kv = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    active, sub, load = kv.get("ActiveState", ""), kv.get("SubState", ""), kv.get("LoadState", "")
    detail = f"{active}/{sub}"
    if load == "not-found":
        return "unknown", "unit not found"
    if active == "active":
        return "running", detail
    if active == "inactive":
        return "stopped", detail
    if active == "failed":
        return "failed", detail
    return "unknown", detail  # activating / deactivating / 解釈不能


def check_systemd(unit: str) -> tuple[str, str]:
    try:
        r = _run(["systemctl", "show", unit, "-p", "ActiveState,SubState,LoadState"])
    except (OSError, subprocess.SubprocessError) as e:
        return "unknown", f"systemctl unavailable: {type(e).__name__}"
    if r.returncode != 0:
        return "unknown", (r.stderr.strip() or "systemctl failed")[:200]
    return parse_systemd(r.stdout)


def parse_docker(output: str) -> tuple[str, str]:
    """`docker inspect <name>` の JSON 出力 -> (state, detail)。"""
    try:
        st = json.loads(output)[0]["State"]
    except (ValueError, LookupError, TypeError):
        return "unknown", "unparsable docker inspect output"
    status = str(st.get("Status", ""))
    health = (st.get("Health") or {}).get("Status")
    detail = f"{status}/{health}" if health else status
    if status in ("running", "paused"):
        return ("failed", detail) if health == "unhealthy" else ("running", detail)
    if status == "restarting":
        return "failed", detail
    if status in ("exited", "dead"):
        return ("failed", detail) if st.get("ExitCode") else ("stopped", detail)
    if status == "created":
        return "stopped", detail
    return "unknown", detail


def check_docker(name: str) -> tuple[str, str]:
    try:
        r = _run(["docker", "inspect", name])
    except (OSError, subprocess.SubprocessError) as e:
        return "unknown", f"docker unavailable: {type(e).__name__}"
    if r.returncode != 0:  # 権限なし・コンテナなし・daemon 停止
        return "unknown", (r.stderr.strip() or "docker inspect failed")[:200]
    return parse_docker(r.stdout)


def check_service(svc: dict) -> dict:
    kind, unit = svc.get("kind"), str(svc.get("unit") or svc.get("id") or "")
    if kind == "systemd":
        state, detail = check_systemd(unit)
    elif kind == "docker":
        state, detail = check_docker(unit)
    else:  # windows_service は PR 14
        state, detail = "unknown", f"unsupported kind: {kind}"
    return {"id": svc.get("id"), "state": state, "detail": detail}


def collect(seq: int, services: list[dict]) -> dict:
    return {
        "type": "telemetry",
        "seq": seq,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resources": collect_resources(),
        "disks": collect_disks(),
        "services": [check_service(s) for s in services],
    }
