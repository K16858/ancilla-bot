"""
AgentLoop
"""

from typing import Final

from ancilla_bot.llm import AgentResponse, send_chat

EXIT_COMMANDS: Final[set[str]] = {"exit", "quit", ":q"}

SYSTEM_PROMPT: Final[str] = """あなたは思考過程（thought）と最終回答（final_answer）を、次の JSON 形式だけで出力するアシスタントです。
- thought: ユーザーの質問の意図を整理し、どう答えるか考える（内部用。短くてよい）。
- final_answer: ユーザーに表示する日本語の回答本文。
JSON 以外の説明や前後の文章は一切出力しないでください。"""


def is_exit_command(text: str) -> bool:
    """
    REPL を終了するためのコマンドかどうかを判定する。
    """
    normalized = text.strip().lower()
    return normalized in EXIT_COMMANDS


def run_minimal_agent_loop(
    user_input: str,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    """
    AgentLoop

    Args:
        user_input: ユーザーが入力したテキスト。
        conversation_history: 会話履歴 [{"role":"user"|"assistant","content":"..."}, ...]。省略時は空。

    Returns:
        final_answer の文字列。パースに失敗した場合は生の応答テキストを返す。
    """
    history = conversation_history or []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_input},
    ]
    raw = send_chat(messages, format=AgentResponse.model_json_schema())
    try:
        parsed = AgentResponse.model_validate_json(raw)
        return parsed.final_answer
    except Exception:
        return raw

