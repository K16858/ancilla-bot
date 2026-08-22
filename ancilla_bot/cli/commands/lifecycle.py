"""start / stop / restart / status / logs。"""

from __future__ import annotations

import argparse
import sys
import time

from ancilla_bot.cli import envfile, health, process, ux
from ancilla_bot.cli.paths import ensure_runtime_dirs, get_root, log_path


CORE = "core"
ADAPTERS = ("discord", "slack")
ALL_TARGETS = (CORE, *ADAPTERS)


def _normalize_targets(raw: list[str] | None, *, default_core: bool = True) -> list[str]:
    if not raw:
        return [CORE] if default_core else list(ALL_TARGETS)
    out: list[str] = []
    for item in raw:
        name = item.strip().lower()
        if name == "all":
            return list(ALL_TARGETS)
        if name not in ALL_TARGETS:
            raise ValueError(name)
        if name not in out:
            out.append(name)
    return out


def _adapter_configured(name: str) -> bool:
    if name == "discord":
        return bool(envfile.get_value("DISCORD_BOT_TOKEN"))
    if name == "slack":
        return bool(envfile.get_value("SLACK_BOT_TOKEN") and envfile.get_value("SLACK_APP_TOKEN"))
    return True


def cmd_start(args: argparse.Namespace) -> int:
    ensure_runtime_dirs()
    if getattr(args, "foreground", False):
        if getattr(args, "cli", False):
            return ux.fail(
                "Cannot combine --foreground and --cli.",
                cause="--foreground occupies this terminal with Core only.",
            )
        targets = _normalize_targets(getattr(args, "targets", None) or [])
        if targets != [CORE]:
            return ux.fail(
                "Foreground mode supports core only.",
                next_cmds=["ancilla start --foreground"],
            )
        from ancilla_bot.cli.main import run_core_foreground

        return run_core_foreground(args)

    try:
        targets = _normalize_targets(getattr(args, "targets", None) or [])
    except ValueError as e:
        return ux.fail(
            f"Unknown target: {e}",
            next_cmds=["ancilla start", "ancilla start core", "ancilla start all"],
        )

    start_all = bool(getattr(args, "targets", None)) and any(
        t.strip().lower() == "all" for t in (args.targets or [])
    )
    need_core = CORE in targets or any(t in ADAPTERS for t in targets)
    if need_core:
        already = process.is_running(CORE) and health.check_health()
        rc = _start_core(quiet_already=start_all or (CORE not in targets and not start_all))
        if rc != 0:
            return rc
        if start_all:
            print(f"[ok] core      {'running' if already else 'started'}")

    for name in ADAPTERS:
        if name not in targets:
            continue
        if not _adapter_configured(name):
            if start_all:
                print(f"- {name:<9} skipped (not configured)")
                continue
            return ux.fail(
                f"{name} is not configured.",
                cause="Missing required tokens in .env",
                next_cmds=["ancilla setup keys", f"ancilla start {name}"],
            )
        already = process.is_running(name)
        rc = _start_adapter(name, quiet=start_all)
        if rc != 0:
            return rc
        if start_all:
            print(f"[ok] {name:<9} {'running' if already else 'started'}")

    if getattr(args, "cli", False):
        from ancilla_bot.cli.main import run_client_repl

        return run_client_repl(args)
    return 0


def _start_core(*, quiet_already: bool = False) -> int:
    endpoint = health.display_endpoint()
    if process.is_running(CORE):
        if health.check_health():
            if not quiet_already:
                print(f"Core already running (pid={process.get_running_pid(CORE)}).")
                print(f"API ready at {endpoint}")
            return 0
        print("Core process exists but is unhealthy. Restarting...")
        process.stop_process(CORE)

    print("Starting Ancilla Core...")
    try:
        pid = process.spawn_worker(CORE)
    except OSError as e:
        return ux.fail(
            "Failed to start Core.",
            cause=str(e),
            next_cmds=["ancilla doctor", "ancilla logs core"],
        )

    print(f"[ok] Process started (pid {pid})")

    if not health.wait_healthy(timeout_sec=45.0):
        still = process.is_running(CORE)
        if not still:
            return ux.fail(
                "Core exited before becoming healthy.",
                cause="See logs via: ancilla logs core",
                next_cmds=["ancilla logs core", "ancilla setup", "ancilla doctor"],
            )
        process.stop_process(CORE)
        return ux.fail(
            "Core did not become healthy in time.",
            cause=f"Endpoint {health.health_url()} did not respond.",
            next_cmds=["ancilla logs core", "ancilla doctor"],
        )

    print(f"[ok] API ready at {endpoint}")
    return 0


def _start_adapter(name: str, *, quiet: bool = False) -> int:
    if process.is_running(name):
        if not quiet:
            print(f"{name} already running (pid={process.get_running_pid(name)}).")
        return 0

    # ensure core healthy
    if not health.check_health():
        rc = _start_core()
        if rc != 0:
            return rc

    if not quiet:
        print(f"Starting {name}...")
    try:
        pid = process.spawn_worker(name)
    except OSError as e:
        return ux.fail(
            f"Failed to start {name}.",
            cause=str(e),
            next_cmds=[f"ancilla logs {name}", "ancilla doctor"],
        )
    # brief settle
    time.sleep(1.0)
    if not process.is_running(name):
        return ux.fail(
            f"{name} exited immediately.",
            cause=f"See: ancilla logs {name}",
            next_cmds=[f"ancilla logs {name}", "ancilla setup keys"],
        )
    if not quiet:
        print(f"[ok] {name} started (pid {pid})")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    try:
        if not getattr(args, "targets", None):
            targets = [n for n in (*ADAPTERS, CORE) if process.is_running(n)]
            if not targets:
                print("No managed processes running.")
                return 0
        else:
            targets = _normalize_targets(args.targets, default_core=False)
    except ValueError as e:
        return ux.fail(f"Unknown target: {e}", next_cmds=["ancilla stop", "ancilla stop all"])

    expanded: list[str] = []
    for name in targets:
        if name == CORE:
            for a in ADAPTERS:
                if a not in expanded:
                    expanded.append(a)
            if CORE not in expanded:
                expanded.append(CORE)
        elif name not in expanded:
            expanded.append(name)

    order = [n for n in (*ADAPTERS, CORE) if n in expanded]
    for name in order:
        if process.is_running(name) or name in targets:
            print(f"Stopping {name}...")
            process.stop_process(name)
            print(f"[ok] {name} stopped")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    stop_args = argparse.Namespace(targets=getattr(args, "targets", None))
    rc = cmd_stop(stop_args)
    if rc != 0:
        return rc
    start_args = argparse.Namespace(
        targets=getattr(args, "targets", None) or [CORE],
        foreground=False,
        cli=False,
    )
    return cmd_start(start_args)


def cmd_status(_args: argparse.Namespace) -> int:
    print("Ancilla")
    print()
    for name in ALL_TARGETS:
        pid = process.get_running_pid(name)
        label = name.capitalize()
        if name == CORE:
            if pid is None:
                print(f"{label:<10} stopped")
            elif health.check_health():
                print(f"{label:<10} running        pid={pid}   healthy")
            else:
                print(f"{label:<10} unhealthy      pid={pid}")
        else:
            if not _adapter_configured(name):
                print(f"{label:<10} not configured")
            elif pid is None:
                print(f"{label:<10} stopped")
            else:
                print(f"{label:<10} running        pid={pid}")
    print()
    print("Client endpoint:")
    print(f"  {health.display_endpoint()}")
    print()
    print(f"Root: {get_root()}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    name = (getattr(args, "target", None) or CORE).strip().lower()
    if name not in ALL_TARGETS:
        return ux.fail(
            f"Unknown log target: {name}",
            next_cmds=["ancilla logs core", "ancilla logs discord"],
        )
    path = log_path(name)
    if not path.is_file():
        return ux.fail(
            f"No log file for {name} yet.",
            cause=f"Expected under {get_root() / 'data' / 'logs'}",
            next_cmds=["ancilla start"],
        )

    follow = bool(getattr(args, "follow", False))
    if not follow:
        text = path.read_text(encoding="utf-8", errors="replace")
        sys.stdout.write(text)
        if text and not text.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    print(f"Following {name} logs (Ctrl+C to stop)...")
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(0, 2)
        try:
            while True:
                line = fh.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
        except KeyboardInterrupt:
            print()
            return 0


def cmd_worker(args: argparse.Namespace) -> int:
    name = args.worker_name
    if name == CORE:
        from ancilla_bot.cli.main import run_core_worker

        return run_core_worker(args)
    if name == "discord":
        from ancilla_bot.discord_bot import main as discord_main

        discord_main()
        return 0
    if name == "slack":
        from ancilla_bot.slack_bot import main as slack_main

        slack_main()
        return 0
    return ux.fail(f"Unknown worker: {name}")
