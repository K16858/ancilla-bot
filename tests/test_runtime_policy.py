from ancilla_bot.core.run_context import run_source
from ancilla_bot.runtime.policy import check


def test_bash_denied_when_autonomous():
    token = run_source.set("heartbeat")
    try:
        msg = check("bash")
        assert msg is not None and "denied" in msg
    finally:
        run_source.reset(token)


def test_bash_allowed_when_interactive():
    token = run_source.set("user")
    try:
        assert check("bash") is None
    finally:
        run_source.reset(token)


def test_read_tools_allowed_when_autonomous():
    token = run_source.set("idle_reflection")
    try:
        assert check("web_search") is None
        assert check("read_file") is None
        assert check("manage_state") is None
        assert check("notify_user") is None
    finally:
        run_source.reset(token)
