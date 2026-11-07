"""Action カタログ（コードで宣言）と、宣言（homelab.yaml）に基づく解決。

Action は 2 つだけ: logs（直近 N 行）と restart。argv はリストで組み立て、シェル文字列は使わない。
Core の policy / operations と Node の実行側（node/execute.py）が同じ定義を使う。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from ancilla_bot.homelab import inventory as inv

# 先頭は英数字のみ（`-f` のようなオプション注入を防ぐ）。systemd の unit 名と docker のコンテナ名を許す
UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,99}$")
LOG_LINES_DEFAULT = 100
LOG_LINES_MAX = 500


class ActionError(Exception):
    """宣言なし・未対応・引数不正。呼び出し側は fail closed（DENY）として扱う。"""


def _logs_argv(kind: str, unit: str, args: dict) -> list[str]:
    n = str(args["lines"])
    if kind == "systemd":
        return ["journalctl", "-u", unit, "-n", n, "--no-pager", "-o", "short-iso"]
    return ["docker", "logs", "--tail", n, unit]


def _restart_argv(kind: str, unit: str, args: dict) -> list[str]:
    return ["systemctl", "restart", unit] if kind == "systemd" else ["docker", "restart", unit]


def _logs_args(args: dict) -> dict:
    raw = args.get("lines")
    try:
        n = LOG_LINES_DEFAULT if raw in (None, "") else int(raw)
    except (TypeError, ValueError) as e:
        raise ActionError("lines は整数で指定してください") from e
    if isinstance(raw, bool) or not 1 <= n <= LOG_LINES_MAX:
        raise ActionError(f"lines は 1〜{LOG_LINES_MAX} です")
    return {"lines": n}


def _no_args(args: dict) -> dict:
    if any(v not in (None, "") for v in args.values()):
        raise ActionError("この action は引数を取りません")
    return {}


@dataclass(frozen=True)
class Action:
    id: str
    effect: str
    target_kinds: tuple[str, ...]
    normalize: Callable[[dict], dict]  # 引数スキーマ（検証して正規化した dict を返す）
    verify: bool  # 実行後に Phase 2 の状態判定が healthy に戻るか確かめる
    node_argv: Callable[[str, str, dict], list[str]]


CATALOG: dict[str, Action] = {
    "logs": Action("logs", "local_read", ("systemd", "docker"), _logs_args, False, _logs_argv),
    "restart": Action("restart", "privileged", ("systemd", "docker"), _no_args, True, _restart_argv),
}


def build_argv(action: str, kind: str, unit: str, args: dict) -> list[str]:
    """Node も使う。未知 action・未対応 kind・不正な unit・不正な引数は ActionError。"""
    a = CATALOG.get(action)
    if a is None:
        raise ActionError(f"未知の action: {action}")
    if kind not in a.target_kinds:
        raise ActionError(f"kind={kind} は {action} に未対応です")
    if not isinstance(unit, str) or not UNIT_RE.fullmatch(unit):
        raise ActionError("unit 名が不正です")
    return a.node_argv(kind, unit, a.normalize(args if isinstance(args, dict) else {}))


@dataclass(frozen=True)
class Resolved:
    action: str
    target: str
    host_id: str
    kind: str
    unit: str
    mode: str  # homelab.yaml の宣言値
    args: dict


def resolve(action: Any, target: Any, args: dict | None = None) -> Resolved:
    """宣言（homelab.yaml）と突き合わせる。通らなければ ActionError。"""
    action, target = str(action or "").strip(), str(target or "").strip()
    a = CATALOG.get(action)
    if a is None:
        raise ActionError(f"未知の action: {action or '(空)'}（{', '.join(CATALOG)}）")
    try:
        i = inv.load_inventory()
    except inv.InventoryError as e:
        raise ActionError(f"homelab.yaml を読めません: {e}") from e
    s = i.service(target)
    if s is None:
        raise ActionError(f"未知のサービス: {target or '(空)'}")
    host = i.host(s.host)
    if host is None or not host.node:
        raise ActionError(f"host '{s.host}' は node: true ではないため操作できません")
    if s.kind not in a.target_kinds:
        raise ActionError(f"kind={s.kind} のサービスは {action} に未対応です")
    mode = s.actions.get(action)
    if mode is None:
        raise ActionError(f"{target} に {action} は許可されていません（homelab.yaml の actions に未宣言）")
    if not UNIT_RE.fullmatch(s.unit or ""):
        raise ActionError(f"{target} の unit 名が不正または未設定です")
    return Resolved(action, target, s.host, s.kind, s.unit, mode, a.normalize(args or {}))


def llm_verdict(action: Any, target: Any, args: dict | None, autonomous: bool) -> tuple[str, str]:
    """LLM が起こす呼び出しの判定 -> ("allow" | "deny" | "require_approval", message)。

    restart は宣言値が auto* でも承認必須（auto は Phase 6 のコード駆動の自動修復用）。自律実行では DENY。
    logs: auto は承認なし（読み取りのみ。自律実行の診断でも可）、approval は自律実行では DENY。
    """
    try:
        r = resolve(action, target, args)
    except ActionError as e:
        return "deny", f"Error: homelab_run_action denied: {e}"
    if r.action == "logs" and r.mode == "auto":
        return "allow", ""
    if autonomous:
        return "deny", f"Error: homelab_run_action {r.action} {r.target} は自律実行では実行できません。"
    return "require_approval", f"Error: homelab_run_action {r.action} {r.target} requires approval."
