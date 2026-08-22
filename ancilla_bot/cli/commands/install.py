"""ancilla install core|client。"""

from __future__ import annotations

import argparse
import sys

from ancilla_bot.cli import envfile, ux
from ancilla_bot.cli.paths import ensure_runtime_dirs, get_root


def cmd_install(args: argparse.Namespace) -> int:
    component = (args.component or "").strip().lower()
    if component == "core":
        return _install_core()
    if component == "client":
        return _install_client(args)
    return ux.fail(
        f"Unknown component: {component or '(none)'}",
        next_cmds=["ancilla install core", "ancilla install client"],
    )


def _install_core() -> int:
    root = get_root()
    ensure_runtime_dirs(root)
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    conv = root / "data" / "conversation"
    conv.mkdir(parents=True, exist_ok=True)
    (root / "data" / "vector_store").mkdir(parents=True, exist_ok=True)
    (root / "data" / "notifications").mkdir(parents=True, exist_ok=True)

    env_path = envfile.env_path(root)
    created_env = not env_path.is_file()
    envfile.ensure_env_file(root)

    print(f"Installed core layout under {root}")
    print(f"  workspace: {workspace}")
    print(f"  data:      {root / 'data'}")
    if created_env:
        print(f"  .env:      created from .env.example")
    else:
        print(f"  .env:      kept existing")
    print()
    print("Next:")
    print("  ancilla setup")
    print("  ancilla start")
    return 0


def _install_client(args: argparse.Namespace) -> int:
    host = getattr(args, "host", None)
    port = getattr(args, "port", None)

    if host is None or port is None:
        if not sys.stdin.isatty():
            return ux.fail(
                "Non-interactive install requires --host and --port.",
                next_cmds=["ancilla install client --host 127.0.0.1 --port 8765"],
            )
        host = host or input("Core host [127.0.0.1]: ").strip() or "127.0.0.1"
        port_s = str(port) if port is not None else input("Core port [8765]: ").strip() or "8765"
        try:
            port = int(port_s)
        except ValueError:
            return ux.fail("Port must be an integer.", next_cmds=["ancilla install client --port 8765"])
    else:
        port = int(port)

    url = f"http://{host}:{port}"
    envfile.ensure_env_file()
    changed = envfile.set_values({"ANCILLA_CORE_URL": url})
    print(f"Client endpoint set to {url}")
    if changed:
        print(f"Updated: {', '.join(changed)}")
    print()
    print("Next:")
    print("  ancilla")
    print("  ancilla setup api")
    return 0
