"""CLI: ancilla api token create|revoke|list"""

from __future__ import annotations

import argparse
import sys

from ancilla_bot.homelab import store


def cmd_api(args: argparse.Namespace) -> int:
    action = args.token_command
    if action == "create":
        print(store.create_api_token(args.name, args.role))
        print("(このトークンは再表示できません。同名で再発行すると古いトークンは失効します)", file=sys.stderr)
    elif action == "revoke":
        ok = store.revoke_api_token(args.name)
        print("失効しました" if ok else "有効なトークンがありません")
        return 0 if ok else 1
    else:
        for t in store.list_api_tokens():
            print(f"{t['name']}\t{t['role']}\t{'revoked' if t['revoked_at'] else 'active'}\tcreated={t['created_at']}")
    return 0
