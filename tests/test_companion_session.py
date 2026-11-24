from __future__ import annotations

import pytest

from ancilla_bot.assistant import companion_session
from ancilla_bot.core.agent_loop import compose_run_system
from ancilla_bot.core.execution import AgentRuntime, ConversationBusy
from ancilla_bot.memory import conversation_store


@pytest.fixture(autouse=True)
def _clean_sessions():
    companion_session.clear_sessions()
    yield
    companion_session.clear_sessions()


def test_companion_history_is_isolated_from_main_history(monkeypatch):
    save_calls: list[object] = []
    monkeypatch.setattr(
        "ancilla_bot.memory.conversation_store.save_active_history",
        lambda hist: save_calls.append(hist),
    )

    seen_histories: list[list[dict[str, str]]] = []

    def runner(user_input: str, history: list[dict[str, str]]):
        seen_histories.append([dict(m) for m in history])
        return f"応答: {user_input}", "happy"

    rt = AgentRuntime()
    res = companion_session.handle_companion_message(
        "こんにちは",
        session_id="tab-1",
        agent_runtime=rt,
        runner=runner,
    )
    assert res == {
        "reply": "応答: こんにちは",
        "emotion": "happy",
        "end_conversation": False,
        "session_id": "tab-1",
    }
    assert seen_histories == [[]]
    assert save_calls == []
    assert conversation_store.load_active_history() == []


def test_companion_history_trims_to_max_turns():
    rt = AgentRuntime()
    for i in range(8):
        companion_session.handle_companion_message(
            f"turn-{i}",
            session_id="trim",
            agent_runtime=rt,
            runner=lambda msg, _hist: (f"reply-{msg}", None),
        )

    hist = companion_session.get_session_history("trim")
    assert len(hist) == companion_session.MAX_TURNS * 2
    assert hist[0] == {"role": "user", "content": "turn-2"}
    assert hist[-1] == {"role": "assistant", "content": "reply-turn-7"}


def test_companion_session_expires_after_ttl(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(companion_session, "_clock", lambda: now[0])
    rt = AgentRuntime()

    companion_session.handle_companion_message(
        "3分タイマー",
        session_id="ttl",
        agent_runtime=rt,
        runner=lambda _m, _h: ("セットしました", None),
    )
    assert len(companion_session.get_session_history("ttl")) == 2

    now[0] += companion_session.SESSION_TTL_SEC + 1
    assert companion_session.get_session_history("ttl") == []

    seen: list[list[dict[str, str]]] = []

    def runner(msg: str, history: list[dict[str, str]]):
        seen.append(history)
        return "はい", None

    companion_session.handle_companion_message(
        "新しい質問",
        session_id="ttl",
        agent_runtime=rt,
        runner=runner,
    )
    assert seen == [[]]


def test_end_session_and_reset_pending_cancel_incomplete_followup_only():
    rt = AgentRuntime()
    companion_session.handle_companion_message(
        "タイマーセットして",
        session_id="slot",
        agent_runtime=rt,
        runner=lambda _m, _h: ("何分にしますか？", None),
    )
    assert companion_session.end_session("slot") is True
    assert companion_session.end_session("missing") is False

    seen: list[list[dict[str, str]]] = []

    def runner2(msg: str, history: list[dict[str, str]]):
        seen.append(history)
        return "今日の予定はありません", "calm"

    res = companion_session.handle_companion_message(
        "今日の予定は？",
        session_id="slot",
        agent_runtime=rt,
        runner=runner2,
    )
    assert res["emotion"] == "calm"
    assert len(seen[0]) == 3
    assert seen[0][0]["content"] == "タイマーセットして"
    assert seen[0][1]["content"] == "何分にしますか？"
    assert seen[0][2]["role"] == "system"
    assert "キャンセル" in seen[0][2]["content"]

    # Explicit reset_pending=True also injects the cancellation note while keeping completed history
    seen.clear()
    companion_session.handle_companion_message(
        "続けて天気は？",
        session_id="slot",
        reset_pending=True,
        agent_runtime=rt,
        runner=runner2,
    )
    assert seen[0][-1]["role"] == "system"
    # Saved history does not persist synthetic system notes
    saved = companion_session.get_session_history("slot")
    assert all(m["role"] in ("user", "assistant") for m in saved)


def test_end_phrases_and_marker():
    assert companion_session.is_end_conversation_phrase("ありがとう。") is True
    assert companion_session.is_end_conversation_phrase("また後で！") is True
    assert companion_session.is_end_conversation_phrase("タイマー止めて") is False

    rt = AgentRuntime()
    res1 = companion_session.handle_companion_message(
        "バイバイ！",
        session_id="end1",
        agent_runtime=rt,
        runner=lambda _m, _h: ("またお話ししましょう", "happy"),
    )
    assert res1["end_conversation"] is True
    assert res1["reply"] == "またお話ししましょう"

    res2 = companion_session.handle_companion_message(
        "そろそろおしまい",
        session_id="end2",
        agent_runtime=rt,
        runner=lambda _m, _h: ("お疲れさまでした。[END_CONVERSATION]", "smile"),
    )
    assert res2["end_conversation"] is True
    assert res2["reply"] == "お疲れさまでした。"
    assert res2["emotion"] == "smile"
    saved = companion_session.get_session_history("end2")
    assert saved[-1]["content"] == "お疲れさまでした。"


def test_voice_companion_does_not_trigger_approval_command(monkeypatch):
    approve_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ancilla_bot.runtime.approval.approve_run",
        lambda run_id, by="cli": approve_calls.append((run_id, by)) or "ok",
    )

    rt = AgentRuntime()
    received: list[str] = []

    def runner(msg: str, _hist: list[dict[str, str]]):
        received.append(msg)
        return "音声では承認できません。", None

    res = companion_session.handle_companion_message(
        "approve r1",
        session_id="auth",
        agent_runtime=rt,
        runner=runner,
    )
    assert approve_calls == []
    assert received == ["approve r1"]
    assert res["reply"] == "音声では承認できません。"


def test_companion_busy_raises_conversation_busy():
    rt = AgentRuntime()
    rt.begin("interactive")
    try:
        with pytest.raises(ConversationBusy):
            companion_session.handle_companion_message(
                "もしもし",
                agent_runtime=rt,
                runner=lambda _m, _h: ("ok", None),
            )
    finally:
        rt.end()


def test_companion_empty_message_raises_value_error():
    rt = AgentRuntime()
    with pytest.raises(ValueError):
        companion_session.handle_companion_message("   ", agent_runtime=rt)


def test_compose_run_system_for_companion_includes_voice_rules_and_memory(monkeypatch):
    monkeypatch.setattr("ancilla_bot.core.agent_loop.build_tools_system_prompt", lambda: "BASE")
    monkeypatch.setattr(
        "ancilla_bot.core.agent_loop.retrieve_context",
        lambda q, ctx: f"MEM:{q}:{ctx.task_id}",
    )

    prompt = compose_run_system("タイマー", task_key="companion:t1", source="companion")
    assert "BASE" in prompt
    assert "音声コンパニオン応答ルール" in prompt
    assert "[END_CONVERSATION]" in prompt
    assert "MEM:タイマー:companion:t1" in prompt

    normal = compose_run_system("タイマー", task_key="t1", source="cli")
    assert normal == "BASE\n\nMEM:タイマー:t1"
