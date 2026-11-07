"""Node-A: Core からの命令を二重チェックして実行する。

Core が乗っ取られても、ここのローカル許可リスト（ANCILLA_NODE_ALLOW_RESTART / ANCILLA_NODE_ALLOW_LOGS）
にない unit は触れない。拒否は fail closed（許可リストが空 = 何も許さない）。
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable

from ancilla_bot.homelab import actions

OUTPUT_MAX = 8000
DEDUPE_MAX = 200
EXEC_TIMEOUT_SEC = 60


def _csv(name: str) -> frozenset[str]:
    return frozenset(x.strip() for x in os.getenv(name, "").split(",") if x.strip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tail(text: str) -> str:
    return text if len(text) <= OUTPUT_MAX else "...(truncated)\n" + text[-OUTPUT_MAX:]


class Executor:
    def __init__(
        self,
        host_id: str,
        allow_restart: frozenset[str] = frozenset(),
        allow_logs: frozenset[str] = frozenset(),
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    ) -> None:
        self.host_id = host_id
        self.allow = {"restart": frozenset(allow_restart), "logs": frozenset(allow_logs)}
        self._run = runner
        self._lock = threading.Lock()
        # ponytail: 重複排除の記憶はメモリのみ。Node 再起動で失われるが、命令の期限（既定 120 秒）が二重実行の窓を縛る
        self._done: OrderedDict[str, dict] = OrderedDict()

    @classmethod
    def from_env(cls, host_id: str) -> "Executor":
        return cls(host_id, _csv("ANCILLA_NODE_ALLOW_RESTART"), _csv("ANCILLA_NODE_ALLOW_LOGS"))

    def _reject(self, cmd: dict, error: str) -> dict:
        return {"type": "command_result", "id": str(cmd.get("id", "")), "ok": False, "output": "",
                "error": f"rejected: {error}", "started_at": _now(), "finished_at": _now()}

    def _check(self, cmd: dict) -> str | None:
        if not cmd.get("id"):
            return "id がありません"
        if cmd.get("host_id") != self.host_id:
            return "別の host 宛ての命令です"
        try:
            exp = datetime.fromisoformat(str(cmd.get("expires_at")))
            if exp.tzinfo is None or datetime.now(timezone.utc) >= exp:
                return "期限切れです"
        except ValueError:
            return "expires_at が不正です"
        action = cmd.get("action")
        if not isinstance(action, str) or action not in actions.CATALOG:
            return f"未知の action: {action}"
        if not isinstance(cmd.get("unit"), str) or cmd["unit"] not in self.allow[action]:
            return f"{cmd.get('unit')} は Node のローカル許可リストにありません"
        return None

    def handle(self, cmd: dict) -> dict:
        """同じ id は再実行せず前の結果を返す（拒否も記憶する）。実行中の再送は完了を待って同じ結果を返す。"""
        if not isinstance(cmd, dict):
            return self._reject({}, "命令の形式が不正です")
        cid = str(cmd.get("id", ""))
        with self._lock:
            if cid in self._done:
                return self._done[cid]
            res = self._execute(cmd)
            if cid:
                self._done[cid] = res
                while len(self._done) > DEDUPE_MAX:
                    self._done.popitem(last=False)
            return res

    def _execute(self, cmd: dict) -> dict:
        err = self._check(cmd)
        if err:
            return self._reject(cmd, err)
        try:
            argv = actions.build_argv(cmd["action"], str(cmd.get("kind")), cmd["unit"], cmd.get("args") or {})
        except actions.ActionError as e:
            return self._reject(cmd, str(e))
        started = _now()
        try:
            p = self._run(argv, capture_output=True, text=True, timeout=EXEC_TIMEOUT_SEC, shell=False)
            ok, out, error = p.returncode == 0, (p.stdout or "") + (p.stderr or ""), ""
            if not ok:
                error = f"exit code {p.returncode}"
        except (OSError, subprocess.SubprocessError) as e:
            ok, out, error = False, "", f"{type(e).__name__}: {e}"
        return {"type": "command_result", "id": cmd["id"], "ok": ok, "output": _tail(out), "error": error,
                "started_at": started, "finished_at": _now()}
