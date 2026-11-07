"""CLI: ancilla homelab hosts|services|inspect|check|node-token|node-revoke|nodes"""

from __future__ import annotations

import argparse
import sys

from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store


def cmd_homelab(args: argparse.Namespace) -> int:
    action = getattr(args, "homelab_command", None)
    try:
        if action == "autoheal":  # homelab.yaml が壊れていても止められるようにする
            from ancilla_bot.homelab import autoheal

            if args.switch != "status":
                autoheal.set_enabled(args.switch == "on")
            print("autoheal: " + ("on" if autoheal.is_enabled() else "off"))
            return 0
        i = inv.load_inventory()
        if action == "node-token":
            h = i.host(args.host)
            if h is None or not h.node:
                print(f"Error: '{args.host}' は homelab.yaml に無いか node: true ではありません")
                return 1
            print(store.issue_token(h.id))
            print("(このトークンは再表示できません。再発行すると古いトークンは失効します)", file=sys.stderr)
        elif action == "node-revoke":
            ok = store.revoke(args.host)
            print("失効しました（接続中の Node は 10 秒以内に切断されます）" if ok else "有効なトークンがありません")
            return 0 if ok else 1
        elif action == "nodes":
            for n in store.list_nodes():
                state = "revoked" if n["revoked_at"] else "connected" if n["connected"] else "disconnected"
                print(
                    f"{n['host_id']}	{state}	last_seen={n['last_seen'] or '-'}"
                    f"	os={n['os'] or '-'}	version={n['version'] or '-'}"
                )
        elif action == "status":
            from ancilla_bot.homelab.status import homelab_get_status

            print(homelab_get_status(args.id))
        elif action == "events":
            from ancilla_bot.homelab.events import homelab_get_events

            print(homelab_get_events(args.subject))
        elif action in ("incidents", "incident", "ack", "resolve"):
            from ancilla_bot.homelab import incidents

            out = {
                "incidents": lambda: incidents.homelab_list_incidents(all=args.all),
                "incident": lambda: incidents.homelab_get_incident(args.id),
                "ack": lambda: incidents.acknowledge(args.id),
                "resolve": lambda: incidents.resolve(args.id),
            }[action]()
            print(out)
            return 1 if out.startswith("Error") else 0
        elif action == "diagnose":
            from ancilla_bot.homelab import diagnose, incidents

            iid = incidents.fmt_id(incidents.parse_id(args.id) or 0)
            if incidents.homelab_get_incident(iid).startswith("Error"):
                print(f"Error: {args.id} は存在しません")
                return 1
            ok = diagnose.diagnose(iid)
            print(incidents.homelab_get_incident(iid) if ok else "診断未実施（LLM が使えないか失敗しました）")
            return 0 if ok else 1
        elif action == "hosts":
            print(inv.format_hosts(i))
        elif action == "services":
            print(inv.format_services(i, getattr(args, "host", "") or ""))
        elif action == "inspect":
            print(inv.format_inspect(i, args.id))
        elif action == "check":
            print(f"OK: hosts={len(i.hosts)} services={len(i.services)} ({inv.inventory_path()})")
        else:
            print(f"Error: unknown homelab command: {action}")
            return 1
    except inv.InventoryError as e:
        print(f"Error: {e}")
        return 1
    return 0
