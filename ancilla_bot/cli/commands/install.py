"""ancilla install core|client。"""

from __future__ import annotations

import argparse
import getpass
import shutil
import subprocess
import sys
from pathlib import Path

from ancilla_bot.cli import envfile, ux
from ancilla_bot.cli.paths import ensure_runtime_dirs, ensure_workspace, get_root


def cmd_install(args: argparse.Namespace) -> int:
    component = (args.component or "").strip().lower()
    if component == "core":
        return _install_core()
    if component == "client":
        return _install_client(args)
    if component == "node":
        return _install_node(args)
    return ux.fail(
        f"Unknown component: {component or '(none)'}",
        next_cmds=["ancilla install core", "ancilla install client", "ancilla install node"],
    )


def _ensure_character(root: Path) -> bool:
    path = root / "data" / "prompts" / "CHARACTER.md"
    if path.is_file():
        return False
    example = root / "data" / "prompts" / "CHARACTER.md.example"
    if not example.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _install_core() -> int:
    root = get_root()
    ensure_runtime_dirs(root)
    workspace = ensure_workspace(root)
    conv = root / "data" / "conversation"
    conv.mkdir(parents=True, exist_ok=True)
    (root / "data" / "vector_store").mkdir(parents=True, exist_ok=True)
    (root / "data" / "notifications").mkdir(parents=True, exist_ok=True)
    created_character = _ensure_character(root)

    env_path = envfile.env_path(root)
    created_env = not env_path.is_file()
    envfile.ensure_env_file(root)

    print(f"Installed core layout under {root}")
    print(f"  workspace: {workspace}")
    print(f"  data:      {root / 'data'}")
    if created_character:
        print("  CHARACTER.md: created from CHARACTER.md.example")
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


NODE_SERVICE = "ancilla-node"
WIN_TASK = "AncillaNode"


def node_unit_text(user: str, root: Path, exe: str) -> str:
    # ProtectSystem=strict は全体が読み取り専用。main() が root 配下（data/ ログ等）に書くので root だけ許可する
    return f"""[Unit]
Description=Ancilla Node
After=network-online.target
Wants=network-online.target

[Service]
User={user}
WorkingDirectory={root}
Environment=ANCILLA_ROOT={root}
ExecStart={exe} node
Restart=always
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths={root}

[Install]
WantedBy=multi-user.target
"""


def schtasks_create_cmd(exe: str) -> list[str]:
    """Windows の常駐方式: タスクスケジューラ（ログオン時起動）。

    Windows Service は pywin32/nssm が要り、管理者権限も必要になるため採らない。
    ONLOGON + /RL LIMITED は現在ユーザーで管理者権限なしに登録できる。
    schtasks では失敗時の自動再起動を簡潔に書けないので、再接続はデーモン自身に任せる。
    """
    return ["schtasks", "/Create", "/TN", WIN_TASK, "/SC", "ONLOGON", "/RL", "LIMITED",
            "/TR", f'"{exe}" node', "/F"]


def _install_node_windows(root: Path) -> int:
    exe = shutil.which("ancilla") or str(Path(sys.argv[0]).resolve())
    try:
        subprocess.run(schtasks_create_cmd(exe), check=True, capture_output=True, text=True)
        subprocess.run(["schtasks", "/Run", "/TN", WIN_TASK], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        return ux.fail(f"タスクスケジューラ登録に失敗しました: {e}", next_cmds=["ancilla node"])
    print(f"タスク {WIN_TASK}（ログオン時に起動）を登録して起動しました。")
    print(f"  状態: schtasks /Query /TN {WIN_TASK}")
    print("  Core 側: ancilla homelab nodes")
    return 0


def _sudo(cmd: list[str], **kw) -> None:
    subprocess.run(["sudo", *cmd], check=True, **kw)


def _install_node(args: argparse.Namespace) -> int:
    core, host_id, token = args.core, args.host_id, args.token
    if not (core and host_id and token):
        return ux.fail(
            "install node には --core, --host-id, --token が必要です。",
            next_cmds=["ancilla install node --core wss://core.home.arpa:8768 --host-id node-1 --token <token>"],
        )
    if not core.startswith(("ws://", "wss://")):
        return ux.fail("--core は ws:// か wss:// で始まる URL を指定してください。")
    root = get_root()
    envfile.ensure_env_file(root)
    envfile.set_values(
        {"ANCILLA_NODE_CORE_URL": core, "ANCILLA_NODE_HOST_ID": host_id, "ANCILLA_NODE_TOKEN": token},
        path=envfile.env_path(root),
    )
    print(f"Node settings written to {envfile.env_path(root)}")

    if sys.platform == "win32":
        return _install_node_windows(root)
    if not sys.platform.startswith("linux"):
        print("常駐登録は Linux / Windows のみ対応です。")
        print("手動実行: ancilla node")
        return 0

    exe = shutil.which("ancilla") or str(Path(sys.argv[0]).resolve())
    unit = node_unit_text(getpass.getuser(), root, exe)
    try:
        _sudo(["tee", f"/etc/systemd/system/{NODE_SERVICE}.service"], input=unit, text=True, stdout=subprocess.DEVNULL)
        _sudo(["systemctl", "daemon-reload"])
        _sudo(["systemctl", "enable", "--now", NODE_SERVICE])
    except (OSError, subprocess.CalledProcessError) as e:
        return ux.fail(f"systemd 登録に失敗しました: {e}", next_cmds=["ancilla node"])
    print(f"{NODE_SERVICE} を登録して起動しました。")
    print(f"  状態: systemctl status {NODE_SERVICE}")
    print("  Core 側: ancilla homelab nodes")
    return 0
