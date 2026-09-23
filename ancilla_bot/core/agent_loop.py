"""
AgentLoop
"""

import os
from datetime import datetime
from typing import Any, Callable, Final

from loguru import logger

from ancilla_bot.api.ws_server import take_staged_vlm_images
from ancilla_bot.core.cancel import is_cancelled, is_suspended
from ancilla_bot.core.reflection import verify_answer
from ancilla_bot.core.run_context import run_source
from ancilla_bot.heartbeat.db import (
    append_audit_log,
    complete_agent_run_step,
    create_agent_run,
    create_agent_run_step,
    resolve_pending_approval,
    update_agent_run_status,
)
from ancilla_bot.llm import send_chat
from ancilla_bot.llm.tool_adapter import (
    _build_native_tool_message,
    _coerce_user_answer,
    get_tool_caller,
    is_native_tool_mode,
)
from ancilla_bot.memory.conversation_store import is_system_event_content
from ancilla_bot.runtime.policy import gated_call
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
    "Call a tool, or reply with your user-facing message."
)
SUSPENDED_REPLY: Final[str] = "処理を中断し、後で再開します。"

SUMMARY_MAX_LEN = 200

MAX_TOOL_TURNS: Final[int] = int(os.getenv("ANCILLA_MAX_TOOL_TURNS", "60"))

_FORCE_SUMMARY_PROMPT: Final[str] = (
    "Summarize what you have thought and gathered so far, and give the best answer you can."
    " If information is incomplete, say so briefly."
)

EXIT_COMMANDS: Final[set[str]] = {"exit", "quit", ":q", "/bye"}


def _finish_run(run_id: str, status: str, *, last_error: str = "", completed: bool = False) -> None:
    from ancilla_bot.skills.evolution import flush_skill_runs

    update_agent_run_status(run_id, status, last_error=last_error)
    flush_skill_runs(run_id, completed=completed)


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
    token = run_source.set(source)
    from ancilla_bot.runtime.persona import _temporary_persona
    from ancilla_bot.skills.evolution import reset_skill_run_tracking, restore_skill_run_tracking

    persona_token = _temporary_persona.set(_temporary_persona.get())
    skill_tokens = reset_skill_run_tracking()
    try:
        return _run_agent_loop_with_tools(
            user_input,
            conversation_history,
            on_turn=on_turn,
            images=images,
            max_turns=max_turns,
            nag_interval=nag_interval,
            nag_message=nag_message,
            source=source,
            parent_run_id=parent_run_id,
        )
    finally:
        restore_skill_run_tracking(skill_tokens)
        _temporary_persona.reset(persona_token)
        run_source.reset(token)


def _run_agent_loop_with_tools(
    user_input: str,
    conversation_history: list[dict[str, str]] | None,
    *,
    on_turn: Callable[
        [str, str | None, dict[str, Any] | None, str | None], None
    ] | None,
    images: list[str] | None,
    max_turns: int | None,
    nag_interval: int | None,
    nag_message: str | None,
    source: str,
    parent_run_id: str | None,
) -> tuple[str, str | None]:
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
    return _agent_loop_turns(
        run_id=run_id,
        messages=messages,
        on_turn=on_turn,
        images=images,
        max_turns=max_turns,
        nag_interval=nag_interval,
        nag_message=nag_message,
        source=source,
        user_input=user_input,
        start_turn=0,
        turns_since_manage_state=0,
        retry_after_verify=False,
    )


def continue_after_approval(
    run_id: str,
    pending: dict[str, Any],
) -> tuple[str, str | None]:
    """Execute the approved tool and resume the same agent run."""
    from ancilla_bot.core.run_context import run_source

    tool_name = str(pending["tool_name"])
    args = dict(pending.get("args") or {})
    messages: list[dict[str, Any]] = list(pending.get("messages") or [])
    turn = int(pending["turn_index"])
    step_id = int(pending["step_id"])
    source = str(pending.get("source") or "user")
    assistant_raw = str(pending.get("assistant_raw") or "")
    assistant_message = pending.get("assistant_message")

    token = run_source.set(source)
    from ancilla_bot.runtime.persona import _temporary_persona
    from ancilla_bot.skills.evolution import reset_skill_run_tracking, restore_skill_run_tracking

    persona_token = _temporary_persona.set(_temporary_persona.get())
    skill_tokens = reset_skill_run_tracking()
    try:
        func = TOOL_REGISTRY.get(tool_name)
        if func is None:
            resolve_pending_approval(int(pending["id"]), "rejected")
            _finish_run(run_id, "failed", last_error=f"unknown tool: {tool_name}")
            return f"Error: unknown tool {tool_name}", None

        update_agent_run_status(run_id, "running")
        try:
            result = func(**args)
            step_status = "tool_succeeded"
        except Exception as e:
            result = f"Error: {e!s}"
            step_status = "tool_failed"
            from ancilla_bot.skills.evolution import note_tool_failure

            note_tool_failure()

        resolve_pending_approval(int(pending["id"]), "approved")
        complete_agent_run_step(
            step_id,
            step_status,
            observation=result,
            error=result if step_status != "tool_succeeded" else "",
        )
        write_event(
            run_id,
            step_status,
            turn_index=turn,
            payload={"action": tool_name, "result": result, "approved": True},
        )

        tool_content = result
        observation = f"Observation: {result}"
        if is_native_tool_mode() and isinstance(assistant_message, dict):
            messages.append(assistant_message)
            messages.append(_build_native_tool_message(assistant_message, tool_content))
        else:
            messages.append({"role": "assistant", "content": assistant_raw})
            messages.append({"role": "user", "content": observation})

        return _agent_loop_turns(
            run_id=run_id,
            messages=messages,
            on_turn=None,
            images=None,
            max_turns=None,
            nag_interval=None,
            nag_message=None,
            source=source,
            user_input="",
            start_turn=turn + 1,
            turns_since_manage_state=0,
            retry_after_verify=False,
        )
    finally:
        restore_skill_run_tracking(skill_tokens)
        _temporary_persona.reset(persona_token)
        run_source.reset(token)


def _agent_loop_turns(
    *,
    run_id: str,
    messages: list[dict[str, Any]],
    on_turn: Callable[
        [str, str | None, dict[str, Any] | None, str | None], None
    ] | None,
    images: list[str] | None,
    max_turns: int | None,
    nag_interval: int | None,
    nag_message: str | None,
    source: str,
    user_input: str,
    start_turn: int,
    turns_since_manage_state: int,
    retry_after_verify: bool,
) -> tuple[str, str | None]:
    tool_caller = get_tool_caller()
    effective_max_turns = max_turns if max_turns is not None else MAX_TOOL_TURNS
    _turns_since_manage_state = turns_since_manage_state

    for turn in range(start_turn, effective_max_turns):
        if is_cancelled():
            write_event(run_id, "run_cancelled", turn_index=turn)
            _finish_run(run_id, "cancelled")
            return "処理をキャンセルしました。", None
        if is_suspended():
            write_event(run_id, "run_suspended", turn_index=turn)
            _finish_run(run_id, "suspended")
            from ancilla_bot.core.execution import get_runtime

            get_runtime().note_suspended(run_id)
            return SUSPENDED_REPLY, None
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
            if is_cancelled():
                write_event(run_id, "run_cancelled", turn_index=turn)
                _finish_run(run_id, "cancelled")
                return "処理をキャンセルしました。", None
            if is_suspended():
                write_event(run_id, "run_suspended", turn_index=turn)
                _finish_run(run_id, "suspended")
                from ancilla_bot.core.execution import get_runtime

                get_runtime().note_suspended(run_id)
                return SUSPENDED_REPLY, None
            logger.warning("tool caller failed: {} ", e)
            write_event(run_id, "run_failed", turn_index=turn, payload={"error": str(e)})
            _finish_run(run_id, "failed", last_error=str(e))
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
        logger.debug("LLM raw={}", (raw or "")[:500] + "..." if len(raw or "") > 500 else raw)
        if (
            not (raw or "").strip()
            and not parsed_result.action
            and not (parsed_result.final_answer or "").strip()
        ):
            logger.warning("LLM returned empty response")
            write_event(run_id, "run_failed", turn_index=turn, payload={"error": "empty LLM response"})
            complete_agent_run_step(step_id, "failed", error="empty LLM response")
            _finish_run(run_id, "failed", last_error="empty LLM response")
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
                _finish_run(run_id, "completed", completed=True)
                return user_answer, parsed_result.emotion
            do_verify = (
                VERIFY_ANSWER
                and not is_system_event_content(user_input)
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
            _finish_run(run_id, "completed", completed=True)
            return user_answer, parsed_result.emotion

        if parsed_result.action == "finish":
            args = parsed_result.action_input or {}
            user_answer = str(args.get("message") or parsed_result.raw or "").strip()
            if not user_answer:
                user_answer = (parsed_result.thought or "").strip()
            logger.info("finish returned len={}", len(user_answer))
            write_event(
                run_id,
                "final_answer",
                turn_index=turn,
                payload={"final_answer": user_answer},
            )
            complete_agent_run_step(step_id, "completed", observation=user_answer)
            _finish_run(run_id, "completed", completed=True)
            return user_answer, parsed_result.emotion

        if parsed_result.action and parsed_result.action in TOOL_REGISTRY:
            func = TOOL_REGISTRY[parsed_result.action]
            args = parsed_result.action_input or {}
            logger.info("tool_call action={} args={}", parsed_result.action, args)
            write_event(
                run_id,
                "tool_called",
                turn_index=turn,
                payload={"action": parsed_result.action, "action_input": args},
            )
            append_audit_log(parsed_result.action, str(args))
            try:
                step_status, result = gated_call(parsed_result.action, func, args)
                if step_status == "approval_pending":
                    from ancilla_bot.runtime.approval import save_pending_approval

                    complete_agent_run_step(
                        step_id, step_status, observation=result, error=result
                    )
                    write_event(
                        run_id,
                        step_status,
                        turn_index=turn,
                        payload={"action": parsed_result.action, "result": result},
                    )
                    msg = save_pending_approval(
                        run_id=run_id,
                        tool_name=parsed_result.action,
                        args=args,
                        turn_index=turn,
                        step_id=step_id,
                        messages=messages,
                        assistant_raw=raw or "",
                        assistant_message=parsed_result.assistant_message
                        if is_native_tool_mode()
                        else None,
                        source=source,
                    )
                    if on_turn is not None:
                        on_turn(parsed_result.thought, parsed_result.action, args, msg)
                    return msg, None

                tool_content = result
                observation = f"Observation: {result}"
                summary = result[:SUMMARY_MAX_LEN] + "..." if len(result) > SUMMARY_MAX_LEN else result
                logger.info("tool_result status={} summary={!r}", step_status, summary)
                logger.debug("tool_result full observation={!r}", observation[:500])
                write_event(
                    run_id,
                    step_status,
                    turn_index=turn,
                    payload={"action": parsed_result.action, "result": result},
                )
                if step_status == "tool_succeeded":
                    complete_agent_run_step(step_id, step_status, observation=result)
                else:
                    if step_status == "tool_failed":
                        from ancilla_bot.skills.evolution import note_tool_failure

                        note_tool_failure()
                    complete_agent_run_step(
                        step_id, step_status, observation=result, error=result
                    )
            except Exception as e:
                tool_content = f"Error: {e!s}"
                observation = f"Observation: {tool_content}"
                logger.warning("tool exception action={} error={}", parsed_result.action, e)
                from ancilla_bot.skills.evolution import note_tool_failure

                note_tool_failure()
                write_event(
                    run_id,
                    "tool_failed",
                    turn_index=turn,
                    payload={"action": parsed_result.action, "error": str(e)},
                )
                complete_agent_run_step(step_id, "tool_failed", error=str(e))
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
                from ancilla_bot.skills.evolution import note_tool_failure

                note_tool_failure()
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
    try:
        summary_msgs = list(messages) + [{"role": "user", "content": _FORCE_SUMMARY_PROMPT}]
        raw_summary = send_chat(summary_msgs, format=None, think=False)
        answer = (raw_summary or "").strip() or "処理を完了できませんでした。"
        _finish_run(run_id, "max_turns")
    except Exception as exc:
        logger.warning("force summary failed: {}", exc)
        write_event(
            run_id,
            "run_failed",
            turn_index=effective_max_turns,
            payload={"error": str(exc)},
        )
        _finish_run(run_id, "failed", last_error=str(exc))
        answer = "処理を完了できませんでした。"
    write_event(
        run_id,
        "final_answer",
        turn_index=effective_max_turns,
        payload={"final_answer": answer},
    )
    return answer, None
