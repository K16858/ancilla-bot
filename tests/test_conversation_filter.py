from ancilla_bot.memory.conversation_store import (
    filter_system_event_messages,
    is_system_event_content,
)


def test_is_system_event_prefix():
    assert is_system_event_content("[SYSTEM_EVENT idle]")
    assert not is_system_event_content("hello")


def test_filter_drops_system_event_pair():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "user", "content": "[SYSTEM_EVENT heartbeat] ping"},
        {"role": "assistant", "content": "pong"},
        {"role": "assistant", "content": "ok"},
    ]
    out = filter_system_event_messages(messages)
    assert out == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
    ]


def test_filter_drops_system_event_user_only():
    messages = [
        {"role": "user", "content": "[SYSTEM_EVENT idle]"},
        {"role": "user", "content": "next"},
    ]
    assert filter_system_event_messages(messages) == [{"role": "user", "content": "next"}]
