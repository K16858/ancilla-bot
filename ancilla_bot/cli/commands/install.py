"""ancilla install core|client。"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from ancilla_bot.cli import envfile, ux
from ancilla_bot.cli.paths import ensure_runtime_dirs, ensure_workspace, get_root
from ancilla_bot.homelab.actions import UNIT_RE


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


def schtasks_create_cmd(xml_path: str) -> list[str]:
    return ["schtasks", "/Create", "/TN", WIN_TASK, "/XML", xml_path, "/F"]


def task_xml(exe: str, user: str, workdir: str) -> str:
    """Windows の常駐方式: タスクスケジューラ（ログオン時起動）のタスク XML。

    Windows Service は pywin32/nssm が要り、管理者権限も必要になるため採らない。
    現在ユーザーの LogonTrigger + LeastPrivilege は管理者権限なしに登録でき、昇格もしない。
    既定の実行時間制限（72h で強制終了）とバッテリー時停止を無効にし、失敗時は 1 分間隔で再起動する。
    """
    e = xml_escape
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{e(user)}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{e(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{e(exe)}</Command><Arguments>node</Arguments><WorkingDirectory>{e(workdir)}</WorkingDirectory></Exec></Actions>
</Task>
"""


def _install_node_windows(root: Path) -> int:
    exe = shutil.which("ancilla") or str(Path(sys.argv[0]).resolve())
    user = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser() if os.environ.get("USERDOMAIN") else getpass.getuser()
    fd, xml_path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(task_xml(exe, user, str(root)))
        subprocess.run(schtasks_create_cmd(xml_path), check=True, capture_output=True, text=True)
        subprocess.run(["schtasks", "/Run", "/TN", WIN_TASK], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        return ux.fail(f"タスクスケジューラ登録に失敗しました: {e}", next_cmds=["ancilla node"])
    finally:
        os.unlink(xml_path)
    print(f"タスク {WIN_TASK}（ログオン時に起動）を登録して起動しました。")
    print(f"  状態: schtasks /Query /TN {WIN_TASK}")
    print("  Core 側: ancilla homelab nodes")
    return 0


POLKIT_RULE_PATH = "/etc/polkit-1/rules.d/50-ancilla-node.rules"
_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}$")


def polkit_rules_text(user: str, units: list[str]) -> str:
    """Node が `systemctl restart <unit>` を非 root で実行するための polkit ルール（unit ごとに 1 条件）。

    計画の「unit ごとの sudoers 1 行」からの変更: Node の systemd unit は NoNewPrivileges=yes で、
    sudo（setuid）が効かない。polkit は systemd 側（PID 1）が認可するので NoNewPrivileges と両立する。
    許可は manage-units の restart verb × 列挙した unit × Node 実行ユーザーだけ。
    """
    if not _USER_RE.fullmatch(user):
        raise ValueError(f"ユーザー名が不正です: {user}")
    names = []
    for u in units:
        if not UNIT_RE.fullmatch(u):
            raise ValueError(f"unit 名が不正です: {u}")
        names.append(u if u.endswith(".service") else f"{u}.service")
    if not names:
        return ""
    conds = " ||\n            ".join(f'action.lookup("unit") == "{n}"' for n in names)
    return f"""// ancilla install node が生成。Node ユーザーに、下記 unit の restart だけを許可する
polkit.addRule(function(action, subject) {{
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "{user}" &&
        action.lookup("verb") == "restart" &&
        (
            {conds}
        )) {{
        return polkit.Result.YES;
    }}
}});
"""


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


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
    allow_restart, allow_logs = _csv(getattr(args, "allow_restart", None)), _csv(getattr(args, "allow_logs", None))
    for u in allow_restart + allow_logs:
        if not UNIT_RE.fullmatch(u):
            return ux.fail(f"--allow-restart / --allow-logs の unit 名が不正です: {u}")
    root = get_root()
    envfile.ensure_env_file(root)
    envfile.set_values(
        {"ANCILLA_NODE_CORE_URL": core, "ANCILLA_NODE_HOST_ID": host_id, "ANCILLA_NODE_TOKEN": token,
         # Node 側のローカル許可リスト（Core が乗っ取られてもここにない unit は触れない）。毎回上書きする
         "ANCILLA_NODE_ALLOW_RESTART": ",".join(allow_restart), "ANCILLA_NODE_ALLOW_LOGS": ",".join(allow_logs)},
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
        rules = polkit_rules_text(getpass.getuser(), allow_restart)
        if rules:
            _sudo(["tee", POLKIT_RULE_PATH], input=rules, text=True, stdout=subprocess.DEVNULL)
        else:  # 許可リストを空にして再インストールしたら古いルールを消す
            _sudo(["rm", "-f", POLKIT_RULE_PATH])
        _sudo(["tee", f"/etc/systemd/system/{NODE_SERVICE}.service"], input=unit, text=True, stdout=subprocess.DEVNULL)
        _sudo(["systemctl", "daemon-reload"])
        _sudo(["systemctl", "enable", "--now", NODE_SERVICE])
    except (OSError, subprocess.CalledProcessError) as e:
        return ux.fail(f"systemd 登録に失敗しました: {e}", next_cmds=["ancilla node"])
    if allow_logs:
        print("ログ取得 (journalctl) には Node 実行ユーザーが systemd-journal グループに必要です（自動では変更しません）:")
        print(f"  sudo usermod -aG systemd-journal {getpass.getuser()}   # 反映にはサービス再起動が必要")
    print(f"{NODE_SERVICE} を登録して起動しました。")
    print(f"  状態: systemctl status {NODE_SERVICE}")
    print("  Core 側: ancilla homelab nodes")
    return 0
