"""Companion mode isolated short-term voice conversation session manager."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading
import time
from typing import Any, Callable

from ancilla_bot.core.agent_loop import run_agent_loop_with_tools
from ancilla_bot.core.cancel import reset_cancel
from ancilla_bot.core.execution import AgentRuntime, ConversationBusy, get_runtime

MAX_TURNS = 6
SESSION_TTL_SEC = 1800

_END_MARKER = "[END_CONVERSATION]"
_TRAILING_PUNCT_RE = re.compile(r"[\s。．.!！?？、,〜～~]+$")
_END_PHRASES = frozenset(
    {
        "終了",
        "終わり",
        "おわり",
        "会話終了",
        "バイバイ",
        "ばいばい",
        "さようなら",
        "さよなら",
        "じゃあね",
        "またね",
        "またあとで",
        "また後で",
        "おやすみ",
        "おやすみなさい",
        "もういい",
        "もういいよ",
        "もういいです",
        "もう大丈夫",
        "もう大丈夫です",
        "それで大丈夫",
        "それで大丈夫です",
        "それでいい",
        "それでいいよ",
        "それでいいです",
        "以上",
        "以上です",
        "ありがとう",
        "ありがとうございます",
        "ありがとうございました",
        "どうもありがとう",
        "サンキュー",
    }
)
_RESET_PENDING_NOTE = (
    "前の会話セッションは一度終了しています。"
    "直前の未完了の聞き返しや確認待ちはキャンセル済みなので引き継がず、"
    "今回の発話を新しい依頼として扱ってください。"
    "完了済みの直近の文脈が必要な場合のみ直前の履歴を参照してください。"
)

CompanionRunner = Callable[[str, list[dict[str, str]]], tuple[str, str | None]]


@dataclass
class _Session:
    history: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = 0.0
    ended: bool = False


_sessions_lock = threading.Lock()
_sessions: dict[str, _Session] = {}


def _clock() -> float:
    return time.monotonic()


def _normalize_session_id(session_id: str | None) -> str:
    return (session_id or "").strip() or "default"


def is_end_conversation_phrase(text: str) -> bool:
    """Return True when the user utterance explicitly closes the conversation."""
    normalized = _TRAILING_PUNCT_RE.sub("", (text or "").strip())
    return normalized in _END_PHRASES


def _extract_end_marker(reply: str | None) -> tuple[str, bool]:
    text = reply or ""
    if _END_MARKER not in text:
        return text.strip(), False
    return text.replace(_END_MARKER, "").strip(), True


def _prune_expired_locked(sid: str, now: float) -> _Session | None:
    session = _sessions.get(sid)
    if session is None:
        return None
    if now - session.updated_at >= SESSION_TTL_SEC:
        _sessions.pop(sid, None)
        return None
    return session


def end_session(session_id: str = "default") -> bool:
    """Mark a companion session ended, keeping completed history for follow-ups."""
    sid = _normalize_session_id(session_id)
    now = _clock()
    with _sessions_lock:
        session = _prune_expired_locked(sid, now)
        if session is None:
            return False
        session.ended = True
        return True


def clear_sessions() -> None:
    """Clear all in-memory companion sessions."""
    with _sessions_lock:
        _sessions.clear()


def get_session_history(session_id: str = "default") -> list[dict[str, str]]:
    """Return a copy of active (non-expired) companion history messages."""
    sid = _normalize_session_id(session_id)
    now = _clock()
    with _sessions_lock:
        session = _prune_expired_locked(sid, now)
        if session is None:
            return []
        return [dict(m) for m in session.history]


def handle_companion_message(
    message: str,
    *,
    session_id: str = "default",
    reset_pending: bool = False,
    agent_runtime: AgentRuntime | None = None,
    runner: CompanionRunner | None = None,
) -> dict[str, Any]:
    """Process one Companion voice/chat turn in an isolated session.

    Voice/companion turns do NOT evaluate text approval commands
    (`try_handle_approval_command`) and do NOT read or mutate the main
    CLI/Discord `conversation_history`.
    """
    user_text = (message or "").strip()
    if not user_text:
        raise ValueError("message must not be empty")

    sid = _normalize_session_id(session_id)
    now = _clock()
    with _sessions_lock:
        session = _prune_expired_locked(sid, now)
        history_snapshot = [dict(m) for m in session.history] if session else []
        should_inject_reset = bool(history_snapshot) and (
            (session.ended if session else False) or reset_pending
        )

    loop_history = list(history_snapshot)
    if should_inject_reset:
        loop_history.append({"role": "system", "content": _RESET_PENDING_NOTE})

    runtime = agent_runtime or get_runtime()
    if runtime.current_kind() == "interactive":
        raise ConversationBusy("interactive conversation in progress")

    runtime.preempt_for_interactive()
    reset_cancel()
    failed = False
    try:
        if runner is not None:
            reply, emotion = runner(user_text, loop_history)
        else:
            reply, emotion = run_agent_loop_with_tools(
                user_text,
                loop_history,
                source="companion",
                task_key=f"companion:{sid}",
            )
    except Exception:
        failed = True
        raise
    finally:
        runtime.end(failed=failed)

    clean_reply, has_marker = _extract_end_marker(reply)
    end_conversation = has_marker or is_end_conversation_phrase(user_text)

    updated_at = _clock()
    with _sessions_lock:
        current = _prune_expired_locked(sid, updated_at)
        if current is None:
            current = _Session()
            _sessions[sid] = current
        current.history.extend(
            [
                {"role": "user", "content": user_text},
                {"role": "assistant", "content": clean_reply},
            ]
        )
        max_messages = MAX_TURNS * 2
        if len(current.history) > max_messages:
            current.history = current.history[-max_messages:]
        current.updated_at = updated_at
        current.ended = end_conversation

    return {
        "reply": clean_reply,
        "emotion": emotion,
        "end_conversation": end_conversation,
        "session_id": sid,
    }
