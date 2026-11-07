"""HomeLab の状態判定と内蔵ヘルスチェック。判定は純粋関数（LLM なし）。

SubjectStatus（Phase 3 が主体ごとに前回と比較する）:
    id, type("host"|"service"), state("healthy"|"degraded"|"unhealthy"|"unknown"),
    flags(["node_lost"]), evidence([{source, freshness, observed_at, values}]), mismatches([str])
state と flags が比較対象。evidence / mismatches は変化時の写し用。

Node 状態を持たない Service（kind が http / other、Host が node: false、Node が報告しない、
Node が state=unknown を返す）は、ヘルスチェックだけで決める: 成功 = healthy、失敗 = unhealthy、
ヘルスチェックも fresh でなければ unknown。
Node が fresh で running の Service にヘルスチェックが無い、または fresh でない場合は healthy。
node_lost のとき Host は degraded（生きているが Node が落ちている。unhealthy にはしない）。
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store
from ancilla_bot.homelab.channel import REPORT_INTERVAL_SEC

FRESH_FACTOR = 3  # 最終受信から報告間隔の 3 倍以内なら fresh
DISK_DEGRADED = 90.0
MEMORY_DEGRADED = 95.0
DISK_UNHEALTHY = 97.0
HEALTH_TIMEOUT_SEC = 5.0
_NODE_KINDS = {"systemd", "docker", "windows_service"}


@dataclass
class SubjectStatus:
    id: str
    type: str
    state: str
    flags: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)


# ---- 内蔵ヘルスチェック ----

def check_url(client: httpx.Client, url: str) -> dict:
    try:
        r = client.get(url)
        return {"ok": 200 <= r.status_code < 400, "status": r.status_code, "error": ""}
    except httpx.HTTPError as e:
        return {"ok": False, "status": None, "error": f"{type(e).__name__}: {e}"}


def check_all(i: inv.Inventory, client: httpx.Client) -> None:
    # ponytail: 逐次実行。数十サービスで 1 周が報告間隔を超えるなら ThreadPool に切り替える
    for s in i.services:
        if s.health_url:
            store.put_observation(s.id, "health", check_url(client, s.health_url))


def run_health_loop(interval: float = REPORT_INTERVAL_SEC, stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    with httpx.Client(timeout=HEALTH_TIMEOUT_SEC, follow_redirects=False) as client:
        while not stop.is_set():
            try:
                check_all(inv.load_inventory(), client)
            except Exception as e:  # inventory 不正でもループは止めない
                logger.warning("health check failed: {}", e)
            stop.wait(interval)


def on_telemetry(host_id: str, msg: dict) -> None:
    store.put_observation(host_id, "node", msg)


# ---- 判定 ----

def _freshness(observed_at: str | None, now: datetime, interval: float) -> str:
    if not observed_at:
        return "missing"
    age = (now - datetime.fromisoformat(observed_at)).total_seconds()
    return "fresh" if age <= FRESH_FACTOR * interval else "stale"


def _ev(source: str, obs, now, interval, values) -> dict:
    at = obs[1] if obs else None
    return {"source": source, "freshness": _freshness(at, now, interval), "observed_at": at,
            "values": values if obs else None}


def evaluate_all(
    now: datetime | None = None,
    interval: float = REPORT_INTERVAL_SEC,
    i: inv.Inventory | None = None,
    observations: dict | None = None,
) -> dict[str, SubjectStatus]:
    now = now or datetime.now()
    i = i or inv.load_inventory()
    obs = store.get_observations() if observations is None else observations
    out: dict[str, SubjectStatus] = {}
    fresh = lambda o: o is not None and _freshness(o[1], now, interval) == "fresh"  # noqa: E731

    for s in i.services:
        host = i.host(s.host)
        node = obs.get((s.host, "node"))
        health = obs.get((s.id, "health")) if s.health_url else None
        node_fresh, health_fresh = fresh(node), fresh(health)
        health_ok = bool(health_fresh and health[0].get("ok"))
        health_bad = bool(health_fresh and not health[0].get("ok"))
        mism: list[str] = []
        reported = None
        if s.kind in _NODE_KINDS and not (host and host.node):
            mism.append(f"kind={s.kind} は Node で観測するが host '{s.host}' は node: false")
        elif s.kind in _NODE_KINDS and node_fresh:
            reported = next((x for x in node[0].get("services", []) if x.get("id") == s.id), None)
            if reported is None:
                mism.append("宣言されているが Node が報告していない")
            elif reported.get("state") == "unknown":
                mism.append(f"Node が状態を取得できない: {reported.get('detail', '')}")
        nstate = reported.get("state") if reported and reported.get("state") != "unknown" else None

        if nstate in ("stopped", "failed"):
            state = "unhealthy"
        elif nstate == "running":
            state = "degraded" if health_bad else "healthy"
        elif health_ok:
            state = "healthy"
        elif health_bad:
            state = "unhealthy"
        else:
            state = "unknown"
        ev = [_ev("node", node, now, interval, reported)]
        if s.health_url:
            ev.append(_ev("health", health, now, interval, health[0] if health else None))
        out[s.id] = SubjectStatus(s.id, "service", state, [], ev, mism)

    for h in i.hosts:
        node = obs.get((h.id, "node")) if h.node else None
        checks = [obs.get((s.id, "health")) for s in i.services if s.host == h.id and s.health_url]
        checks = [c for c in checks if fresh(c)]
        flags: list[str] = []
        if h.node and fresh(node):
            res, disks = node[0].get("resources", {}), node[0].get("disks", [])
            worst = max((d.get("percent", 0) for d in disks), default=0)
            mem = res.get("memory_percent", 0) or 0
            state = ("unhealthy" if worst > DISK_UNHEALTHY
                     else "degraded" if worst > DISK_DEGRADED or mem > MEMORY_DEGRADED
                     else "healthy")
            values = {"resources": res, "disks": disks}
        else:
            values = None
            if not checks:
                state = "unknown"
            elif any(c[0].get("ok") for c in checks):
                state = "degraded" if h.node else "healthy"
                if h.node:
                    flags.append("node_lost")
            else:
                state = "unhealthy"
        ev = [_ev("node", node, now, interval, values)] if h.node else []
        ev.append({"source": "health", "freshness": "fresh" if checks else "missing",
                   "observed_at": max((c[1] for c in checks), default=None),
                   "values": {s.id: obs[(s.id, "health")][0].get("ok") for s in i.services
                              if s.host == h.id and fresh(obs.get((s.id, "health")))} or None})
        out[h.id] = SubjectStatus(h.id, "host", state, flags, ev, [])
    return out


# ---- ツール / CLI ----

def homelab_get_status(id: str = "", **kwargs: Any) -> str:  # noqa: A002
    _ = kwargs
    try:
        st = evaluate_all()
    except inv.InventoryError as e:
        return f"Error: {e}"
    id = str(id or "").strip()
    if id:
        if id not in st:
            return f"Error: 未知の id: {id}"
        data: Any = asdict(st[id])
    else:
        data = [{"id": x.id, "type": x.type, "state": x.state, "flags": x.flags} for x in st.values()]
    # 観測値は外部由来のデータ。JSON のまま返し、指示としては扱わない
    return json.dumps(data, ensure_ascii=False, indent=2)


def homelab_get_metrics(id: str = "", **kwargs: Any) -> str:  # noqa: A002
    _ = kwargs
    id = str(id or "").strip()
    try:
        if not inv.load_inventory().host(id):
            return f"Error: 未知の host: {id}"
    except inv.InventoryError as e:
        return f"Error: {e}"
    o = store.get_observations().get((id, "node"))
    if not o:
        return f"host '{id}' のテレメトリはまだありません"
    return json.dumps(
        {"host": id, "freshness": _freshness(o[1], datetime.now(), REPORT_INTERVAL_SEC),
         "received_at": o[1], "telemetry": o[0]},
        ensure_ascii=False, indent=2,
    )
