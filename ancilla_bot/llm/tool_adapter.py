"""
ツール呼び出しモード切り替え（GBNF / Ollama native tools）
"""

from __future__ import annotations

import json
import os
from typing import Any, NamedTuple, Protocol

from ancilla_bot.llm.ollama_client import send_chat, send_chat_message
from ancilla_bot.llm.schemas import AgentResponseWithTools
from ancilla_bot.tools.registry import TOOL_DESCRIPTIONS, _short_tool_description
from ancilla_bot.tools.schemas import NATIVE_EXCLUDED_TOOLS, get_native_parameters


class ToolCallResult(NamedTuple):
    action: str | None
    action_input: dict[str, Any] | None
    thought: str
    final_answer: str | None
    emotion: str | None
    raw: str


class ToolCaller(Protocol):
    def call(
        self,
        messages: list[dict[str, Any]],
        *,
        images: list[str] | None = None,
    ) -> ToolCallResult: ...


def _coerce_user_answer(text: str | None) -> str | None:
    """final_answer が JSON 全体になっている場合にユーザー向け本文だけを取り出す。"""
    if not text or not text.strip():
        return text
    s = text.strip()
    if not s.startswith("{"):
        return s
    for candidate in (s, s[s.find("{") : s.rfind("}") + 1] if "{" in s else s):
        try:
            parsed = AgentResponseWithTools.model_validate_json(candidate)
        except Exception:
            continue
        if parsed.final_answer and parsed.final_answer.strip():
            return parsed.final_answer.strip()
        return None
    return s


def _build_ollama_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for name, desc in TOOL_DESCRIPTIONS.items():
        if name in NATIVE_EXCLUDED_TOOLS:
            continue
        short = _short_tool_description(desc)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": short[:1024],
                    "parameters": get_native_parameters(name),
                },
            }
        )
    return tools


def _native_message_to_result(message: dict[str, Any]) -> ToolCallResult:
    content = (message.get("content") or "").strip()
    thinking = (message.get("thinking") or "").strip()
    thought = thinking or content
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        fn = (tool_calls[0].get("function") or {})
        name = fn.get("name")
        args_raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except (json.JSONDecodeError, TypeError):
            args = {}
        raw = json.dumps(
            {"thought": thought, "action": name, "action_input": args, "final_answer": None},
            ensure_ascii=False,
        )
        return ToolCallResult(name, args, thought, None, None, raw)
    raw = json.dumps(
        {"thought": thought, "final_answer": content or None, "action": None, "action_input": None},
        ensure_ascii=False,
    )
    answer = _coerce_user_answer(content) or content or None
    return ToolCallResult(None, None, thought, answer, None, raw)


def _parse_gbnf_response(raw: str) -> ToolCallResult:
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    try:
        parsed = AgentResponseWithTools.model_validate_json(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = AgentResponseWithTools.model_validate_json(text[start : end + 1])
        else:
            return ToolCallResult(None, None, "", text, None, text)
    answer = parsed.final_answer
    if answer:
        answer = _coerce_user_answer(answer) or answer
    return ToolCallResult(
        parsed.action,
        parsed.action_input,
        parsed.thought,
        answer,
        parsed.emotion,
        text,
    )


class GBNFToolCaller:
    """GBNF + JSON Schema でツール呼び出しを制約するモード。"""

    def call(
        self,
        messages: list[dict[str, Any]],
        *,
        images: list[str] | None = None,
    ) -> ToolCallResult:
        schema = AgentResponseWithTools.model_json_schema()
        raw = send_chat(messages, format=schema, images=images)
        return _parse_gbnf_response(raw)


class NativeToolCaller:
    """Ollama tools= パラメータを使うモード。"""

    def __init__(self) -> None:
        self._tools = _build_ollama_tools()

    def call(
        self,
        messages: list[dict[str, Any]],
        *,
        images: list[str] | None = None,
    ) -> ToolCallResult:
        message = send_chat_message(messages, images=images, tools=self._tools)
        return _native_message_to_result(message)


def get_tool_caller() -> ToolCaller:
    mode = os.getenv("ANCILLA_TOOL_MODE", "gbnf").strip().lower()
    return NativeToolCaller() if mode == "native" else GBNFToolCaller()
