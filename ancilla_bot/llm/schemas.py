"""
LLM 応答の構造化用 Pydantic モデル
"""

from typing import Any

from pydantic import BaseModel


class AgentResponse(BaseModel):
    """
    AgentLoop 用の応答形式
    """

    thought: str
    final_answer: str


class AgentResponseWithTools(BaseModel):
    """
    ツール呼び出しありの AgentLoop 用応答形式

    - action / action_input があればツール実行。Observation を返して再呼び出し
    - final_answer があればそこでループ終了
    - emotion は最終回答時の感情
    """

    thought: str
    action: str | None = None
    action_input: dict[str, Any] | None = None
    final_answer: str | None = None
    emotion: str | None = None
