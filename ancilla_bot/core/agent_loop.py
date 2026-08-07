"""
AgentLoop
"""

import os
from datetime import datetime
from typing import Any, Callable, Final

from loguru import logger

from ancilla_bot.api.ws_server import take_staged_vlm_images
from ancilla_bot.core.cancel import is_cancelled, reset_cancel
from ancilla_bot.core.reflection import verify_answer
from ancilla_bot.heartbeat.db import (
    append_audit_log,
    complete_agent_run_step,
    create_agent_run,
    create_agent_run_step,
    update_agent_run_status,
)
from ancilla_bot.llm import AgentResponse, send_chat
from ancilla_bot.llm.schemas import AgentResponseWithTools
from ancilla_bot.llm.tool_adapter import (
    _build_native_tool_message,
    _coerce_user_answer,
    get_tool_caller,
    is_native_tool_mode,
)
from ancilla_bot.memory.conversation_store import is_system_event_content
from ancilla_bot.tools import TOOL_REGISTRY, build_tools_system_prompt
from ancilla_bot.tracing import new_run_id, write_event

VERIFY_ANSWER = os.getenv("ANCILLA_VERIFY_ANSWER", "true").strip().lower() in ("1", "true", "yes")
VERIFY_ONLY_AFTER_TOOL = os.getenv("ANCILLA_VERIFY_ONLY_AFTER_TOOL", "true").strip().lower() in ("1", "true", "yes")
RETRY_USER_MESSAGE: Final[str] = (
    "Self-verification found the answer insufficient. Call a tool once more or revise and output final_answer again."
)
NATIVE_RETRY_USER_MESSAGE: Final[str] = (
    "Self-verification found the answer insufficient. Use a tool once more or revise your reply."
)
NATIVE_MISSING_ACTION_MESSAGE: Final[str] = (
    "Use an available tool or reply to the user in plain Japanese."
)

SUMMARY_MAX_LEN = 200

MAX_TOOL_TURNS: Final[int] = int(os.getenv("ANCILLA_MAX_TOOL_TURNS", "15"))

_FORCE_SUMMARY_PROMPT: Final[str] = (
    "Summarize what you have thought and gathered so far, and give the best answer you can."
    " If information is incomplete, say so briefly."
)

EXIT_COMMANDS: Final[set[str]] = {"exit", "quit", ":q", "/bye"}

SYSTEM_PROMPT: Final[str] = """あなたは思考過程（thought）と最終回答（final_answer）を、次の JSON 形式だけで出力するアシスタントです。
- thought: ユーザーの質問の意図を整理し、どう答えるか考える（内部用。短くてよい）。
- final_answer: ユーザーに表示する日本語の回答本文。
JSON 以外の説明や前後の文章は一切出力しないでください。"""


def _inject_time_note(messages: list[dict[str, str]]) -> None:
    """
    先頭の system メッセージへ現在時刻ノートを付与する。
    system が無ければ先頭に作る。
    """
    if not messages:
        return
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    note = f"[System Note: 現在時刻: {now_str}]"

    if messages[0].get("role") == "system":
        first = dict(messages[0])
        body = first.get("content") or ""
        lines = [
            line
            for line in body.splitlines()
            if not line.startswith("[System Note: 現在時刻:")
        ]
        cleaned = "\n".join(lines).rstrip()
        first["content"] = f"{cleaned}\n\n{note}".strip() if cleaned else note
        messages[0] = first
        return

    messages.insert(0, {"role": "system", "content": note})


def is_exit_command(text: str) -> bool:
    """
    REPL を終了するためのコマンドかどうかを判定する。
    """
    normalized = text.strip().lower()
    return normalized in EXIT_COMMANDS


def _is_system_event_prompt(user_input: str) -> bool:
    """
    擬似ユーザーメッセージ（Fast Heartbeat / Idle Reflection 等）かどうか
    "[SYSTEM_EVENT" で始まるものをすべて対象にする（": IDLE_REFLECTION]" 等も含む）
    """
    return is_system_event_content(user_input)


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
    except Exception as e:
        logger.warning("run_minimal_agent_loop parse failed: {} raw_head={!r}", e, (raw or "")[:200])
        return "応答の解析に失敗しました。もう一度試してください。"


def run_agent_loop_with_tools(
    user_input: str,
    conversation_history: list[dict[str, str]] | None = None,
    *,
    on_turn: Callable[
        [str, str | None, dict[str, Any] | None, str | None], None
    ] | None = None,
    images: list[str] | None = None,
    max_turns: int | None = None,
    nag_interval: int | None = None,
    nag_message: str | None = None,
    source: str = "unknown",
    parent_run_id: str | None = None,
) -> tuple[str, str | None]:
    """
    ツール呼び出しありの ReAct ループ。

    action があればツールを実行し、Observation を LLM に返して再呼び出し。
    final_answer が出るか最大ターン数に達するまで繰り返す。

    on_turn が指定されている場合、各ターンで
    on_turn(thought, action, action_input, observation) を 1 回呼ぶ。
    """
    logger.info("user_input={!r}", user_input[:100] + "..." if len(user_input) > 100 else user_input)
    run_id = new_run_id()
    write_event(
        run_id,
        "run_started",
        payload={
            "source": source,
            "user_input": user_input,
            "has_images": bool(images),
            "parent_run_id": parent_run_id,
        },
    )
    create_agent_run(run_id, source=source, user_input=user_input, parent_run_id=parent_run_id)
    history = list(conversation_history or [])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_tools_system_prompt()},
        *history,
        {"role": "user", "content": user_input},
    ]
    _inject_time_note(messages)
    tool_caller = get_tool_caller()
    retry_after_verify = False
    effective_max_turns = max_turns if max_turns is not None else MAX_TOOL_TURNS
    # nag injection: turns since last manage_state call
    _turns_since_manage_state = 0

    for turn in range(effective_max_turns):
        if is_cancelled():
            write_event(run_id, "run_cancelled", turn_index=turn)
            update_agent_run_status(run_id, "cancelled")
            return "処理をキャンセルしました。", None
        logger.debug("ReAct turn {} messages={}", turn + 1, messages)
        send_images: list[str] | None = None
        if turn == 0 and images:
            send_images = images
        staged = take_staged_vlm_images()
        if staged:
            send_images = staged
        try:
            parsed_result = tool_caller.call(messages, images=send_images)
        except Exception as e:
            logger.warning("tool caller failed: {} ", e)
            write_event(run_id, "run_failed", turn_index=turn, payload={"error": str(e)})
            update_agent_run_status(run_id, "failed", last_error=str(e))
            return "応答の解析に失敗しました。もう一度試してください。", None

        raw = parsed_result.raw
        step_id = create_agent_run_step(
            run_id,
            turn_index=turn,
            status="llm_responded",
            thought=parsed_result.thought,
            action=parsed_result.action,
            action_input=parsed_result.action_input,
        )
        write_event(
            run_id,
            "llm_responded",
            turn_index=turn,
            payload={
                "thought": parsed_result.thought,
                "action": parsed_result.action,
                "action_input": parsed_result.action_input,
                "has_final_answer": bool(parsed_result.final_answer),
            },
        )
        logger.debug("LLM raw={}", raw[:500] + "..." if len(raw) > 500 else raw)
        if not raw or not raw.strip():
            logger.warning("LLM returned empty response")
            write_event(run_id, "run_failed", turn_index=turn, payload={"error": "empty LLM response"})
            complete_agent_run_step(step_id, "failed", error="empty LLM response")
            update_agent_run_status(run_id, "failed", last_error="empty LLM response")
            return (
                "内部エラーが発生しました（空の応答）。少し待ってからもう一度試してください。",
                None,
            )

        if parsed_result.final_answer:
            user_answer = _coerce_user_answer(parsed_result.final_answer) or parsed_result.final_answer
            if retry_after_verify:
                logger.info(
                    "final_answer (after retry) returned len={}",
                    len(user_answer),
                )
                write_event(
                    run_id,
                    "final_answer",
                    turn_index=turn,
                    payload={"final_answer": user_answer},
                )
                complete_agent_run_step(step_id, "completed", observation=user_answer)
                update_agent_run_status(run_id, "completed")
                return user_answer, parsed_result.emotion
            do_verify = (
                VERIFY_ANSWER
                and not _is_system_event_prompt(user_input)
                and (not VERIFY_ONLY_AFTER_TOOL or turn >= 1)
            )
            if do_verify and not verify_answer(user_input, user_answer):
                write_event(
                    run_id,
                    "verification_failed",
                    turn_index=turn,
                    payload={"final_answer": user_answer},
                )
                complete_agent_run_step(step_id, "verification_failed", observation=user_answer)
                if is_native_tool_mode() and parsed_result.assistant_message:
                    messages.append(parsed_result.assistant_message)
                else:
                    messages.append({"role": "assistant", "content": raw})
                retry_msg = (
                    NATIVE_RETRY_USER_MESSAGE if is_native_tool_mode() else RETRY_USER_MESSAGE
                )
                messages.append({"role": "user", "content": retry_msg})
                retry_after_verify = True
                continue
            if on_turn is not None:
                on_turn(parsed_result.thought, None, None, None)
            logger.info("final_answer returned len={}", len(user_answer))
            write_event(
                run_id,
                "final_answer",
                turn_index=turn,
                payload={"final_answer": user_answer},
            )
            complete_agent_run_step(step_id, "completed", observation=user_answer)
            update_agent_run_status(run_id, "completed")
            return user_answer, parsed_result.emotion

        # action が有効ならツール実行
        if parsed_result.action and parsed_result.action in TOOL_REGISTRY:
            func = TOOL_REGISTRY[parsed_result.action]
            args: dict[str, Any] = parsed_result.action_input or {}
            logger.info("tool_call action={} args={}", parsed_result.action, args)
            write_event(
                run_id,
                "tool_called",
                turn_index=turn,
                payload={"action": parsed_result.action, "action_input": args},
            )
            append_audit_log(parsed_result.action, str(args))
            try:
                result = func(**args)
                tool_content = result
                observation = f"Observation: {result}"
                summary = result[:SUMMARY_MAX_LEN] + "..." if len(result) > SUMMARY_MAX_LEN else result
                logger.info("tool_result summary={!r}", summary)
                logger.debug("tool_result full observation={!r}", observation[:500])
                write_event(
                    run_id,
                    "tool_succeeded",
                    turn_index=turn,
                    payload={"action": parsed_result.action, "result": result},
                )
                complete_agent_run_step(step_id, "tool_succeeded", observation=result)
            except Exception as e:
                tool_content = f"Error: {e!s}"
                observation = f"Observation: {tool_content}"
                logger.warning("tool exception action={} error={}", parsed_result.action, e)
                write_event(
                    run_id,
                    "tool_failed",
                    turn_index=turn,
                    payload={"action": parsed_result.action, "error": str(e)},
                )
                complete_agent_run_step(step_id, "tool_failed", error=str(e))
            # nag injection: track agent_tasks usage specifically
            args_table = (parsed_result.action_input or {}).get("table", "")
            if parsed_result.action == "manage_state" and args_table == "agent_tasks":
                _turns_since_manage_state = 0
            else:
                _turns_since_manage_state += 1
            if nag_interval and nag_message and _turns_since_manage_state >= nag_interval:
                if is_native_tool_mode():
                    tool_content += f"\n<reminder>{nag_message}</reminder>"
                else:
                    observation += f"\n<reminder>{nag_message}</reminder>"
                _turns_since_manage_state = 0
            if on_turn is not None:
                on_turn(parsed_result.thought, parsed_result.action, args, observation)
            if is_native_tool_mode() and parsed_result.assistant_message:
                messages.append(parsed_result.assistant_message)
                messages.append(_build_native_tool_message(parsed_result.assistant_message, tool_content))
            else:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": observation})
        else:
            # 未知のツール or action なし
            if parsed_result.action:
                tool_content = f"Unknown tool: {parsed_result.action}"
                observation = f"Observation: {tool_content}"
                logger.warning("unknown tool action={}", parsed_result.action)
                write_event(
                    run_id,
                    "tool_failed",
                    turn_index=turn,
                    payload={"action": parsed_result.action, "error": tool_content},
                )
                complete_agent_run_step(step_id, "tool_failed", error=tool_content)
            else:
                tool_content = ""
                observation = "Observation: action または final_answer を指定してください。"
                logger.warning("action/final_answer missing")
                complete_agent_run_step(step_id, "invalid_response", observation=observation)
            if on_turn is not None:
                on_turn(
                    parsed_result.thought,
                    parsed_result.action,
                    parsed_result.action_input,
                    observation,
                )
            if is_native_tool_mode() and parsed_result.assistant_message:
                messages.append(parsed_result.assistant_message)
                if parsed_result.action:
                    messages.append(
                        _build_native_tool_message(parsed_result.assistant_message, tool_content)
                    )
                else:
                    messages.append({"role": "user", "content": NATIVE_MISSING_ACTION_MESSAGE})
            else:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": observation})

    logger.warning("max turns ({}) reached, forcing final answer", effective_max_turns)
    write_event(run_id, "max_turns_reached", turn_index=effective_max_turns)
    update_agent_run_status(run_id, "max_turns")
    try:
        summary_msgs = list(messages) + [{"role": "user", "content": _FORCE_SUMMARY_PROMPT}]
        raw_summary = send_chat(summary_msgs, format=None, think=False)
        answer = (raw_summary or "").strip() or "処理を完了できませんでした。"
    except Exception as exc:
        logger.warning("force summary failed: {}", exc)
        write_event(
            run_id,
            "run_failed",
            turn_index=effective_max_turns,
            payload={"error": str(exc)},
        )
        update_agent_run_status(run_id, "failed", last_error=str(exc))
        answer = "処理を完了できませんでした。"
    write_event(
        run_id,
        "final_answer",
        turn_index=effective_max_turns,
        payload={"final_answer": answer},
    )
    return answer, None
