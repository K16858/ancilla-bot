"""CLI: ancilla homelab hosts|services|inspect|check"""

from __future__ import annotations

import argparse

from ancilla_bot.homelab import inventory as inv


def cmd_homelab(args: argparse.Namespace) -> int:
    action = getattr(args, "homelab_command", None)
    try:
        i = inv.load_inventory()
        if action == "hosts":
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
