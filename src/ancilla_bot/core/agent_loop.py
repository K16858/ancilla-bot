"""
AgentLoop
"""

from typing import Final


EXIT_COMMANDS: Final[set[str]] = {"exit", "quit", ":q"}


def is_exit_command(text: str) -> bool:
    """
    REPL を終了するためのコマンドかどうかを判定する
    """
    normalized = text.strip().lower()
    return normalized in EXIT_COMMANDS


def run_minimal_agent_loop(user_input: str) -> str:

    return user_input

