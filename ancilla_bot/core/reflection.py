"""
Self-Reflection
"""

import os
import re

from loguru import logger

from ancilla_bot.llm import send_chat

VERIFY_PROMPT = (
    "User question: {user_input}\n"
    "Proposed answer: {final_answer}\n\n"
    "Does this answer satisfy the user's request? Reply with only true or false."
)


def verify_answer(user_input: str, final_answer: str) -> bool:
    """
    提案回答がユーザーの要求を満たしているかを LLM に 1 回だけ判定させる

    Returns:
        True: 満たしている / 曖昧な場合はループ防止のため True 扱い
        False: 満たしていないと判定された。リトライを促す
    """
    prompt = VERIFY_PROMPT.format(
        user_input=user_input[:2000],
        final_answer=final_answer[:4000],
    )
    messages = [
        {"role": "user", "content": prompt},
    ]
    try:
        raw = send_chat(messages, format=None)
    except Exception as e:
        logger.warning("verify_answer LLM error: {} -> treat as true", e)
        return True

    text = (raw or "").strip().lower()
    # 明示的に false を含む文（例 "false", "false."）→ False
    if re.search(r"\bfalse\b", text):
        logger.info("verify_answer result=false")
        return False
    # true または曖昧 → True
    logger.info("verify_answer result=true (or ambiguous)")
    return True
