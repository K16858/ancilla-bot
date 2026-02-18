"""
LLM 応答の構造化用 Pydantic モデル
"""

from pydantic import BaseModel


class AgentResponse(BaseModel):
    """
    AgentLoop 用の応答形式
    """

    thought: str
    final_answer: str
