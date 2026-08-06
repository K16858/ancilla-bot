"""
LLM プロバイダ切替（ollama / openai 互換）
"""

import os

from dotenv import load_dotenv

load_dotenv()

_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
_EMBED_PROVIDER = os.getenv("LLM_EMBED_PROVIDER", _PROVIDER).strip().lower()


def _load_chat(provider: str):
    if provider == "openai":
        from ancilla_bot.llm import openai_client as mod
    elif provider == "ollama":
        from ancilla_bot.llm import ollama_client as mod
    else:
        raise ValueError(f"未対応の LLM_PROVIDER: {provider}（ollama または openai）")
    return mod.send_chat, mod.send_chat_message


def _load_embed(provider: str):
    if provider == "openai":
        from ancilla_bot.llm.openai_client import embed_text
    elif provider == "ollama":
        from ancilla_bot.llm.ollama_client import embed_text
    else:
        raise ValueError(f"未対応の LLM_EMBED_PROVIDER: {provider}（ollama または openai）")
    return embed_text


send_chat, send_chat_message = _load_chat(_PROVIDER)
embed_text = _load_embed(_EMBED_PROVIDER)

__all__ = ["embed_text", "send_chat", "send_chat_message"]
