"""CLI: ancilla timer list|set|stop|cancel"""

from __future__ import annotations

import argparse

from ancilla_bot.assistant import timers


def cmd_timer(args: argparse.Namespace) -> int:
    action = getattr(args, "timer_command", None)
    try:
        if action == "list":
            payload = timers.list_timers_payload(include_finished=bool(getattr(args, "all", False)))
            rows = payload["timers"]
            if not rows:
                print("(タイマーなし)")
                return 0
            for t in rows:
                label = f"\tlabel={t['label']}" if t["label"] else ""
                print(
                    f"{t['id']}\t{t['status']}\trem={t['remaining_sec']}s"
                    f"\tends={t['ends_at']}{label}"
                )
            return 0
        if action == "set":
            t = timers.create_timer(
                args.duration_sec,
                label=getattr(args, "label", "") or "",
                source="cli",
            )
            label = f" ({t['label']})" if t["label"] else ""
            print(f"{t['id']} を設定しました: {t['duration_sec']}秒{label} / ends={t['ends_at']}")
            return 0
        if action == "stop":
            stopped = timers.stop_timer(getattr(args, "id", "") or "")
            if not stopped:
                print("鳴動中のタイマーはありません")
                return 0
            for t in stopped:
                print(f"{t['id']} を停止しました")
            return 0
        if action == "cancel":
            t = timers.cancel_timer(args.id)
            print(f"{t['id']} を取り消しました ({t['status']})")
            return 0
        print(f"Error: unknown timer command: {action}")
        return 1
    except (ValueError, LookupError) as exc:
        print(f"Error: {exc}")
        return 1
