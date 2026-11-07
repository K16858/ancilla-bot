"""クライアント API（/api/v1）の参照系。既存の HomeLab の関数を JSON にして返すだけ。

route(path, query) -> (status, body)。観測時刻は evidence[].observed_at / evaluated_at / last_seen などに載る。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from ancilla_bot.homelab import events, incidents, status
from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store


def _tool(out: str) -> tuple[int, Any]:
    """ツール関数の戻り値（JSON 文字列 / "Error: ..."）を (status, body) にする。"""
    if out.startswith("Error"):
        return (404 if "未知" in out or "存在" in out else 400), {"error": out}
    return 200, json.loads(out)


def route(path: str, q: dict[str, str]) -> tuple[int, Any]:
    parts = [p for p in path[len("/api/v1"):].split("/") if p]
    try:
        if parts == ["nodes"]:
            keep = ("host_id", "connected", "last_seen", "os", "version", "hostname", "issued_at", "revoked_at")
            return 200, [{k: n[k] for k in keep} for n in store.list_nodes()]
        if parts == ["approvals"]:
            from ancilla_bot.runtime import approval
            return 200, approval.list_pending()
        if parts == ["events"]:
            return _tool(events.homelab_get_events(q.get("subject", ""), q.get("since", ""), q.get("limit") or 50))
        if parts == ["incidents"]:
            return _tool(incidents.homelab_list_incidents(all=q.get("all", ""), limit=200))
        if len(parts) == 2 and parts[0] == "incidents":
            return _tool(incidents.homelab_get_incident(parts[1]))

        i = inv.load_inventory()
        sts = {k: asdict(v) for k, v in status.evaluate_all(i=i).items()}
        now = datetime.now().isoformat(timespec="seconds")

        def item(declared, extra: dict | None = None) -> dict:
            d = declared.model_dump()
            return d | {"status": sts[d["id"]], "evaluated_at": now} | (extra or {})

        if parts == ["summary"]:
            def count(t: str) -> dict:
                out: dict[str, int] = {}
                for s in sts.values():
                    if s["type"] == t:
                        out[s["state"]] = out.get(s["state"], 0) + 1
                return out
            sev: dict[str, int] = {}
            for x in json.loads(incidents.homelab_list_incidents(limit=200)):
                sev[x["severity"]] = sev.get(x["severity"], 0) + 1
            return 200, {"evaluated_at": now, "hosts": count("host"), "services": count("service"),
                         "open_incidents": sev}
        if parts == ["hosts"]:
            return 200, [item(h) for h in i.hosts]
        if parts == ["services"]:
            return 200, [item(s) for s in i.services]
        if len(parts) == 2 and parts[0] == "hosts" and i.host(parts[1]):
            h = i.host(parts[1])
            return 200, item(h, {"services": [s.id for s in i.services if s.host == h.id]})
        if len(parts) == 2 and parts[0] == "services" and i.service(parts[1]):
            s = i.service(parts[1])
            return 200, item(s, {"impact": {"dependencies": i.dependencies(s.id), "dependents": i.dependents(s.id)}})
    except inv.InventoryError as e:
        return 503, {"error": str(e)}
    return 404, {"error": "not found"}
