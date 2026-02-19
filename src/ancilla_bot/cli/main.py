"""
Ancilla-Bot CLIエントリーポイント
"""

import argparse

from ancilla_bot.core.agent_loop import is_exit_command, run_agent_loop_with_tools
from ancilla_bot.utils.logging_config import init_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Ancilla-Bot CLI")
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG レベルでログを出力")
    args = parser.parse_args()

    init_logging(level="DEBUG" if args.verbose else "INFO")

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

