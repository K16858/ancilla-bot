from ancilla_bot.core.execution import AgentRuntime


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
