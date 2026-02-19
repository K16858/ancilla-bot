"""
Ancilla-Bot CLIエントリーポイント
"""

import argparse
import os

from dotenv import load_dotenv

from ancilla_bot.core.agent_loop import is_exit_command, run_agent_loop_with_tools
from ancilla_bot.utils.logging_config import init_logging

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ancilla-Bot CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG レベルでログを出力")
    parser.add_argument("--log-file", metavar="PATH", help="ログをファイルにも出力（例: data/logs/ancilla.log）")
    args = parser.parse_args()

    level = "DEBUG" if args.verbose else os.getenv("ANCILLA_LOG_LEVEL", "INFO")
    log_file = args.log_file or os.getenv("ANCILLA_LOG_FILE") or None
    init_logging(level=level, log_file=log_file)

    print("Ancilla CLI を起動しました。終了するには 'exit', 'quit', ':q' のいずれかを入力してください。")
    conversation_history: list[dict[str, str]] = []

    while True:
        try:
            user_input = input("Ancilla CLI > ")
        except (EOFError, KeyboardInterrupt):
            print("\n終了します。")
            break

        if is_exit_command(user_input):
            print("終了コマンドが入力されたため、REPL を終了します。")
            break

        response = run_agent_loop_with_tools(user_input, conversation_history)
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": response})
        print(f"Ancilla: {response}")


if __name__ == "__main__":
    main()

