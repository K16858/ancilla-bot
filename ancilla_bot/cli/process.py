"""マネージドプロセスの spawn / PID / 停止。"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import psutil

from ancilla_bot.cli.paths import ensure_runtime_dirs, get_root, log_path, pid_path

MANAGED_NAMES = ("core", "discord", "slack")


def _is_ancilla_process(proc: psutil.Process) -> bool:
    try:
        cmdline = proc.cmdline()
    except (psutil.Error, OSError):
        return False
    joined = " ".join(cmdline).lower()
    return "ancilla" in joined or "ancilla_bot" in joined


def read_pid(name: str) -> int | None:
    path = pid_path(name)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return int(text)
    except (OSError, ValueError):
        return None


def write_pid(name: str, pid: int) -> None:
    ensure_runtime_dirs()
    path = pid_path(name)
    path.write_text(f"{pid}\n", encoding="utf-8")


def clear_pid(name: str) -> None:
    path = pid_path(name)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def get_running_pid(name: str) -> int | None:
    """生きていて Ancilla らしい PID。stale なら削除して None。"""
    pid = read_pid(name)
    if pid is None:
        return None
    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            clear_pid(name)
            return None
        if not _is_ancilla_process(proc):
            clear_pid(name)
            return None
        return pid
    except psutil.Error:
        clear_pid(name)
        return None


def is_running(name: str) -> bool:
    return get_running_pid(name) is not None


def any_managed_running() -> list[str]:
    return [n for n in MANAGED_NAMES if is_running(n)]


def spawn_worker(name: str, *, extra_args: list[str] | None = None) -> int:
    """`ancilla _worker <name>` をデタッチ起動し PID を返す。"""
    if name not in MANAGED_NAMES:
        raise ValueError(f"unknown worker: {name}")
    ensure_runtime_dirs()
    root = get_root()
    log_file = log_path(name)
    cmd = [sys.executable, "-m", "ancilla_bot.cli", "--log-file", str(log_file), "_worker", name]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    env.setdefault("ANCILLA_ROOT", str(root))
    env["ANCILLA_LOG_FILE"] = str(log_file)

    stdout = open(log_file, "a", encoding="utf-8")
    stderr = subprocess.STDOUT

    kwargs: dict = {
        "cwd": str(root),
        "env": env,
        "stdout": stdout,
        "stderr": stderr,
        "stdin": subprocess.DEVNULL,
        "close_fds": sys.platform != "win32",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000200 | 0x00000008  # NEW_PROCESS_GROUP | DETACHED
        kwargs["close_fds"] = False
    else:
        kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **kwargs)
    stdout.close()
    write_pid(name, proc.pid)
    return proc.pid


def stop_process(name: str, *, timeout_sec: float = 15.0) -> bool:
    """SIGTERM → 待機 → 必要なら kill。成功で True（既に止まっていても True）。"""
    pid = get_running_pid(name)
    if pid is None:
        clear_pid(name)
        return True
    try:
        proc = psutil.Process(pid)
    except psutil.Error:
        clear_pid(name)
        return True

    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
    except psutil.Error:
        clear_pid(name)
        return True

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if not proc.is_running():
            clear_pid(name)
            return True
        time.sleep(0.2)

    try:
        proc.kill()
    except psutil.Error:
        pass
    clear_pid(name)
    return True


def ancilla_argv() -> list[str]:
    """現在のインタプリタで ancilla 相当を起動する argv 先頭。"""
    return [sys.executable, "-m", "ancilla_bot.cli.main"]
