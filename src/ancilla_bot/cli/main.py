"""
Ancilla-Bot CLIエントリーポイント
"""

from ancilla_bot.core.agent_loop import is_exit_command, run_minimal_agent_loop


def main() -> None:
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

        response = run_minimal_agent_loop(user_input, conversation_history)
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": response})
        print(f"Ancilla: {response}")


if __name__ == "__main__":
    main()

