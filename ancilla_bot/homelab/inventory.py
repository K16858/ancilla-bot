"""HomeLab Inventory: 宣言された構成（data/homelab.yaml）の読み込み・検証・照会。読み取り専用。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SLUG = r"^[a-z0-9][a-z0-9_-]*$"


class InventoryError(Exception):
    """読み込み・検証エラー。メッセージに悪い箇所を含む。"""


class Host(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=SLUG)
    name: str
    os: Literal["ubuntu", "arch", "windows", "haos", "other"]
    role: str = ""
    criticality: Literal["high", "normal", "low"] = "normal"
    address: str = ""
    node: bool = False


class Service(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=SLUG)
    name: str
    host: str
    kind: Literal["systemd", "docker", "windows_service", "http", "other"]
    unit: str = ""
    health_url: str = ""
    criticality: Literal["high", "normal", "low"] = "normal"
    depends_on: list[str] = Field(default_factory=list)


class Inventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hosts: list[Host] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=list)

    def host(self, id_: str) -> Host | None:
        return next((h for h in self.hosts if h.id == id_), None)

    def service(self, id_: str) -> Service | None:
        return next((s for s in self.services if s.id == id_), None)

    def dependencies(self, id_: str) -> list[str]:
        """推移的な依存先（自分自身は含まない）。循環があっても止まる。"""
        return self._walk(id_, lambda s: s.depends_on)

    def dependents(self, id_: str) -> list[str]:
        """推移的な依存元（= 止まったときの影響範囲）。"""
        return self._walk(id_, lambda s: [x.id for x in self.services if s.id in x.depends_on])

    def _walk(self, start: str, nxt) -> list[str]:
        seen = {start}
        out: list[str] = []
        stack = [start]
        while stack:
            cur = self.service(stack.pop())
            for n in (nxt(cur) if cur else []):
                if n not in seen:
                    seen.add(n)
                    out.append(n)
                    stack.append(n)
        return out


def _loc(loc: tuple) -> str:
    out = ""
    for p in loc:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out


def parse_inventory(text: str, source: str = "homelab.yaml") -> Inventory:
    try:
        data: Any = yaml.safe_load(text) or {}
    except yaml.YAMLError as e:
        raise InventoryError(f"{source}: YAML として読めません: {e}") from e
    if not isinstance(data, dict):
        raise InventoryError(f"{source}: トップレベルはマッピングにしてください")
    try:
        inv = Inventory.model_validate(data)
    except ValidationError as e:
        errs = [f"{_loc(x['loc'])}: {x['msg']}" for x in e.errors()]
        raise InventoryError(f"{source}: " + "; ".join(errs)) from e
    errs = []
    seen: set[str] = set()
    for kind, items in (("hosts", inv.hosts), ("services", inv.services)):
        for i, it in enumerate(items):
            if it.id in seen:
                errs.append(f"{kind}[{i}].id: ID '{it.id}' が重複しています")
            seen.add(it.id)
    host_ids = {h.id for h in inv.hosts}
    svc_ids = {s.id for s in inv.services}
    for i, s in enumerate(inv.services):
        if s.host not in host_ids:
            errs.append(f"services[{i}].host: 未知の host '{s.host}' (service '{s.id}')")
        for d in s.depends_on:
            if d not in svc_ids:
                errs.append(f"services[{i}].depends_on: 未知の service '{d}' (service '{s.id}')")
    if errs:
        raise InventoryError(f"{source}: " + "; ".join(errs))
    return inv


def inventory_path() -> Path:
    raw = (os.getenv("ANCILLA_HOMELAB_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser()
    from ancilla_bot.cli.paths import get_root

    return get_root() / "data" / "homelab.yaml"


_cache: tuple[Path, float, Inventory] | None = None


def load_inventory() -> Inventory:
    """mtime が変わっていれば読み直す。失敗時は InventoryError。"""
    global _cache
    path = inventory_path()
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as e:
        raise InventoryError(f"{path}: 読み込めません: {e}") from e
    if _cache and _cache[0] == path and _cache[1] == mtime:
        return _cache[2]
    inv = parse_inventory(path.read_text(encoding="utf-8"), str(path))
    _cache = (path, mtime, inv)
    return inv


# ---- 表示（CLI とツール共通）----

def format_hosts(inv: Inventory) -> str:
    if not inv.hosts:
        return "(ホストなし)"
    return "\n".join(
        f"{h.id}: {h.name} os={h.os} criticality={h.criticality} node={str(h.node).lower()} role={h.role}"
        for h in inv.hosts
    )


def format_services(inv: Inventory, host: str = "") -> str:
    if host and not inv.host(host):
        raise InventoryError(f"未知の host: {host}")
    rows = [s for s in inv.services if not host or s.host == host]
    if not rows:
        return "(サービスなし)"
    return "\n".join(
        f"{s.id}: {s.name} host={s.host} kind={s.kind} criticality={s.criticality}"
        + (f" depends_on={','.join(s.depends_on)}" if s.depends_on else "")
        for s in rows
    )


def format_inspect(inv: Inventory, id_: str) -> str:
    h = inv.host(id_)
    if h:
        return f"[host]\n{yaml.safe_dump(h.model_dump(), allow_unicode=True, sort_keys=False)}\n[services]\n" + format_services(inv, id_)
    s = inv.service(id_)
    if not s:
        raise InventoryError(f"未知の id: {id_}")
    deps, impact = inv.dependencies(id_), inv.dependents(id_)
    return (
        f"[service]\n{yaml.safe_dump(s.model_dump(), allow_unicode=True, sort_keys=False)}"
        f"[dependencies(推移)] {', '.join(deps) or '(なし)'}\n"
        f"[止まると影響する service(推移)] {', '.join(impact) or '(なし)'}"
    )


# ---- ツール（エラーは文字列で返す。Core 起動は妨げない）----

def homelab_list_hosts(**kwargs: Any) -> str:
    _ = kwargs
    try:
        return format_hosts(load_inventory())
    except InventoryError as e:
        return f"Error: {e}"


def homelab_list_services(host: str = "", **kwargs: Any) -> str:
    _ = kwargs
    try:
        return format_services(load_inventory(), str(host or "").strip())
    except InventoryError as e:
        return f"Error: {e}"


def homelab_inspect(id: str = "", **kwargs: Any) -> str:  # noqa: A002
    _ = kwargs
    try:
        return format_inspect(load_inventory(), str(id or "").strip())
    except InventoryError as e:
        return f"Error: {e}"
