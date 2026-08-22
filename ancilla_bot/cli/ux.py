"""失敗メッセージの定型（原因 + 次コマンド）。"""

from __future__ import annotations


def fail(message: str, *, cause: str | None = None, next_cmds: list[str] | None = None) -> int:
    """標準エラーに失敗内容を出し、常に非ゼロを返す。"""
    print(message, flush=True)
    if cause:
        print(flush=True)
        print(cause, flush=True)
    if next_cmds:
        print(flush=True)
        if len(next_cmds) == 1:
            print("Next:", flush=True)
        else:
            print("Next:", flush=True)
        for cmd in next_cmds:
            print(f"  {cmd}", flush=True)
    return 1


def ok(message: str) -> int:
    print(message, flush=True)
    return 0
