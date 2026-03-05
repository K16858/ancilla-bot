"""
Ancilla-Bot CLIエントリーポイント
"""

import argparse
import os
import sys
from typing import Any

from dotenv import load_dotenv

from ancilla_bot.core.agent_loop import is_exit_command, run_agent_loop_with_tools
from ancilla_bot.memory.conversation_store import append_overflow, load_active_history, save_active_history
from ancilla_bot.memory.short_term import append_and_trim
from ancilla_bot.utils.logging_config import init_logging

load_dotenv()

REASONING_THOUGHT_MAX = 200
REASONING_OBSERVATION_MAX = 100
DIM = "\033[2m"
RESET = "\033[0m"

# 履歴最大文字数
MAX_HISTORY_CHARS = int(os.getenv("ANCILLA_MAX_HISTORY_CHARS", "4000"))


def _reasoning_line(text: str, dim: bool) -> str:
    if dim and sys.stderr.isatty():
        return f"{DIM}{text}{RESET}"
    return text


def _print_reasoning(
    thought: str,
    action: str | None,
    action_input: dict[str, Any] | None,
    observation: str | None,
) -> None:
    dim = True
    t = (thought or "")[:REASONING_THOUGHT_MAX]
    if len(thought or "") > REASONING_THOUGHT_MAX:
        t += "..."
    if t:
        print(_reasoning_line(f"  thought: {t}", dim))
    if action is not None:
        args_str = str(action_input or {})[:80]
        if len(str(action_input or {})) > 80:
            args_str += "..."
        line = f"  action: {action} ({args_str})"
        if observation:
            obs = observation.replace("Observation: ", "", 1)[:REASONING_OBSERVATION_MAX]
            if len(observation) > REASONING_OBSERVATION_MAX + 12:
                obs += "..."
            line += f" → Observation: {obs}"
        print(_reasoning_line(line, dim))


def _run_repl(args: argparse.Namespace) -> None:
    level = "DEBUG" if args.verbose else os.getenv("ANCILLA_LOG_LEVEL", "INFO")
    log_file = args.log_file or os.getenv("ANCILLA_LOG_FILE") or None
    init_logging(level=level, log_file=log_file)

    print("Ancilla CLI を起動しました。終了するには 'exit', 'quit', ':q' のいずれかを入力してください。")
    conversation_history: list[dict[str, str]] = load_active_history()
    on_turn = _print_reasoning if args.show_reasoning else None

    try:
        while True:
            try:
                user_input = input("Ancilla CLI > ")
            except (EOFError, KeyboardInterrupt):
                print("\n終了します。")
                break

            if is_exit_command(user_input):
                print("終了コマンドが入力されたため、REPL を終了します。")
                break

            response = run_agent_loop_with_tools(user_input, conversation_history, on_turn=on_turn)
            user_msg = {"role": "user", "content": user_input}
            assistant_msg = {"role": "assistant", "content": response}
            dropped = append_and_trim(
                conversation_history,
                [user_msg, assistant_msg],
                max_chars=MAX_HISTORY_CHARS,
            )
            if dropped:
                append_overflow(dropped)
            print(f"Ancilla: {response}")
    finally:
        save_active_history(conversation_history)


def _run_batch_summarize() -> None:
    from ancilla_bot.batch.summarize import run_summarize

    run_summarize()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ancilla-Bot CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG レベルでログを出力")
    parser.add_argument("--log-file", metavar="PATH", help="ログをファイルにも出力（例: data/logs/ancilla.log）")
    parser.add_argument("-r", "--show-reasoning", action="store_true", help="thought とツール呼び出しを薄く表示")
    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    batch_parser = subparsers.add_parser("batch", help="バッチ処理")
    batch_sub = batch_parser.add_subparsers(dest="batch_command", required=True)
    batch_sub.add_parser("summarize", help="会話を結合し summaries に出力")

    args = parser.parse_args()

    if args.command == "batch":
        if args.batch_command == "summarize":
            _run_batch_summarize()
        return

    _run_repl(args)


if __name__ == "__main__":
    main()

