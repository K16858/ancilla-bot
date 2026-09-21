import pytest

from ancilla_bot.cli import main as cli_main
from ancilla_bot.core.execution import AgentRuntime, ConversationBusy


def test_wait_first_reply_timeout_is_silent():
    rt = AgentRuntime()
    rt.begin("interactive")
    try:
        assert rt.wait_first_reply(0.05) is None
        assert rt._returned_early
    finally:
        rt.end()


def test_wait_first_reply_returns_offered_text():
    rt = AgentRuntime()
    rt.begin("interactive")
    try:
        rt.offer_first_reply("hello")
        assert rt.wait_first_reply(0.05) == "hello"
        assert not rt._returned_early
    finally:
        rt.end()


def test_busy_interactive_raises_and_queues():
    rt = AgentRuntime()
    rt.begin("interactive")
    cli_main.PENDING_MESSAGES.clear()
    try:
        with pytest.raises(ConversationBusy):
            cli_main._handle_message("hi", [], rt, 1000, None, source="api")
        assert cli_main.PENDING_MESSAGES == [
            {"input": "hi", "images": None, "source": "api"}
        ]
    finally:
        rt.end()
        cli_main.PENDING_MESSAGES.clear()
