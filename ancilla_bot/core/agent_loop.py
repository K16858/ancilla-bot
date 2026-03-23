"""
AgentLoop
"""

import os
from datetime import datetime
from typing import Any, Callable, Final

from loguru import logger

from ancilla_bot.api.ws_server import take_staged_vlm_images
from ancilla_bot.core.reflection import verify_answer
from ancilla_bot.heartbeat.db import append_audit_log
from ancilla_bot.llm import AgentResponse, AgentResponseWithTools, send_chat
from ancilla_bot.tools import TOOL_REGISTRY, build_tools_system_prompt

VERIFY_ANSWER = os.getenv("ANCILLA_VERIFY_ANSWER", "true").strip().lower() in ("1", "true", "yes")
VERIFY_ONLY_AFTER_TOOL = os.getenv("ANCILLA_VERIFY_ONLY_AFTER_TOOL", "true").strip().lower() in ("1", "true", "yes")
RETRY_USER_MESSAGE: Final[str] = (
    "Self-verification found the answer insufficient. Call a tool once more or revise and output final_answer again."
)

SUMMARY_MAX_LEN = 200

MAX_TOOL_TURNS: Final[int] = int(os.getenv("ANCILLA_MAX_TOOL_TURNS", "5"))

_FORCE_SUMMARY_PROMPT: Final[str] = (
    "これまでの思考と収集した情報をもとに、わかっている範囲で日本語で回答してください。"
    "情報が不完全な場合もその旨を含めて答えてください。"
)

EXIT_COMMANDS: Final[set[str]] = {"exit", "quit", ":q", "/bye"}

SYSTEM_PROMPT: Final[str] = """あなたは思考過程（thought）と最終回答（final_answer）を、次の JSON 形式だけで出力するアシスタントです。
- thought: ユーザーの質問の意図を整理し、どう答えるか考える（内部用。短くてよい）。
- final_answer: ユーザーに表示する日本語の回答本文。
JSON 以外の説明や前後の文章は一切出力しないでください。"""


def _inject_time_note(messages: list[dict[str, str]]) -> None:
    """
    messages の末尾にあるユーザーメッセージの直前に、現在時刻の System Note を挿入する。
    ユーザーメッセージが見つからない場合は末尾に追加する。
    """
    if not messages:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    content = f"[System Note: 現在時刻: {now_str}]"
    note = {"role": "system", "content": content}

    # 最後の user メッセージを探す（通常は末尾）
    last_user_idx = None
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.get("role") == "user":
            last_user_idx = idx
            break

    if last_user_idx is None:
        messages.append(note)
        return

    messages.insert(last_user_idx, note)


def is_exit_command(text: str) -> bool:
    """
    REPL を終了するためのコマンドかどうかを判定する。
    """
    normalized = text.strip().lower()
    return normalized in EXIT_COMMANDS


def _is_system_event_prompt(user_input: str) -> bool:
    """
    擬似ユーザーメッセージ（Fast Heartbeat / Idle Reflection 等）かどうか
    """
    return (user_input or "").strip().startswith("[SYSTEM_EVENT]")


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


def run_agent_loop_with_tools(
    user_input: str,
    conversation_history: list[dict[str, str]] | None = None,
    *,
    on_turn: Callable[
        [str, str | None, dict[str, Any] | None, str | None], None
    ] | None = None,
    images: list[str] | None = None,
) -> tuple[str, str | None]:
    """
    ツール呼び出しありの ReAct ループ。

    action があればツールを実行し、Observation を LLM に返して再呼び出し。
    final_answer が出るか最大ターン数に達するまで繰り返す。

    on_turn が指定されている場合、各ターンで
    on_turn(thought, action, action_input, observation) を 1 回呼ぶ。
    """
    logger.info("user_input={!r}", user_input[:100] + "..." if len(user_input) > 100 else user_input)
    history = list(conversation_history or [])
    messages: list[dict[str, str]] = [
        {"role": "system", "content": build_tools_system_prompt()},
        *history,
        {"role": "user", "content": user_input},
    ]
    _inject_time_note(messages)
    schema = AgentResponseWithTools.model_json_schema()
    retry_after_verify = False

    for turn in range(MAX_TOOL_TURNS):
        logger.debug("ReAct turn {} messages={}", turn + 1, messages)
        send_images: list[str] | None = None
        if turn == 0 and images:
            send_images = images
        staged = take_staged_vlm_images()
        if staged:
            send_images = staged
        raw = send_chat(messages, format=schema, images=send_images)
        logger.debug("LLM raw={}", raw[:500] + "..." if len(raw) > 500 else raw)
        try:
            if not raw or not raw.strip():
                logger.warning("LLM returned empty response for AgentResponseWithTools")
                return (
                    "内部エラーが発生しました（空の応答）。少し待ってからもう一度試してください。",
                    None,
                )
            parsed = AgentResponseWithTools.model_validate_json(raw)
        except Exception as e:
            logger.warning("parse failed: {} raw_len={}", e, len(raw))
            return raw, None

        if parsed.final_answer:
            if retry_after_verify:
                logger.info("final_answer (after retry) returned len={}", len(parsed.final_answer))
                return parsed.final_answer, parsed.emotion
            do_verify = (
                VERIFY_ANSWER
                and not _is_system_event_prompt(user_input)
                and (not VERIFY_ONLY_AFTER_TOOL or turn >= 1)
            )
            if do_verify and not verify_answer(user_input, parsed.final_answer):
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": RETRY_USER_MESSAGE})
                retry_after_verify = True
                continue
            if on_turn is not None:
                on_turn(parsed.thought, None, None, None)
            logger.info("final_answer returned len={}", len(parsed.final_answer))
            return parsed.final_answer, parsed.emotion

        # action が有効ならツール実行
        if parsed.action and parsed.action in TOOL_REGISTRY:
            func = TOOL_REGISTRY[parsed.action]
            args: dict[str, Any] = parsed.action_input or {}
            logger.info("tool_call action={} args={}", parsed.action, args)
            append_audit_log(parsed.action, str(args))
            try:
                result = func(**args)
                observation = f"Observation: {result}"
                summary = result[:SUMMARY_MAX_LEN] + "..." if len(result) > SUMMARY_MAX_LEN else result
                logger.info("tool_result summary={!r}", summary)
                logger.debug("tool_result full observation={!r}", observation[:500])
            except Exception as e:
                observation = f"Observation: Error: {e!s}"
                logger.warning("tool exception action={} error={}", parsed.action, e)
            if on_turn is not None:
                on_turn(parsed.thought, parsed.action, args, observation)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": observation})
        else:
            # 未知のツール or action なし
            if parsed.action:
                observation = f"Observation: Unknown tool: {parsed.action}"
                logger.warning("unknown tool action={}", parsed.action)
            else:
                observation = "Observation: action または final_answer を指定してください。"
                logger.warning("action/final_answer missing")
            if on_turn is not None:
                on_turn(parsed.thought, parsed.action, parsed.action_input, observation)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": observation})

    logger.warning("max turns reached, forcing final answer")
    try:
        summary_msgs = list(messages) + [{"role": "user", "content": _FORCE_SUMMARY_PROMPT}]
        raw_summary = send_chat(summary_msgs, format=None)
        answer = (raw_summary or "").strip() or "処理を完了できませんでした。"
    except Exception as exc:
        logger.warning("force summary failed: {}", exc)
        answer = "処理を完了できませんでした。"
    return answer, None
