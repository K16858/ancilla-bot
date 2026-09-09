from ancilla_bot.core.run_context import run_source
from ancilla_bot.runtime import policy
from ancilla_bot.runtime.policy import ALLOW, DENY, REQUIRE_APPROVAL, check, decide, gated_call


def test_bash_denied_when_autonomous():
    token = run_source.set("heartbeat")
    try:
        decision = decide("bash")
        assert decision.verdict == DENY
        assert "denied" in (check("bash") or "")
    finally:
        run_source.reset(token)


def test_bash_allowed_when_interactive():
    token = run_source.set("user")
    try:
        assert decide("bash").verdict == ALLOW
        assert check("bash") is None
    finally:
        run_source.reset(token)


def test_read_tools_allowed_when_autonomous():
    token = run_source.set("idle_reflection")
    try:
        assert decide("web_search").verdict == ALLOW
        assert decide("read_file").verdict == ALLOW
        assert decide("manage_state").verdict == ALLOW
        assert decide("notify_user").verdict == ALLOW
    finally:
        run_source.reset(token)


def test_gated_call_deny_does_not_run_tool():
    token = run_source.set("heartbeat")
    called = {"n": 0}

    def boom(**kwargs):
        called["n"] += 1
        return "ran"

    try:
        status, result = gated_call("bash", boom, {"command": "echo hi"})
    finally:
        run_source.reset(token)
    assert status == "policy_denied"
    assert "denied" in result
    assert called["n"] == 0


def test_gated_call_require_approval(monkeypatch):
    monkeypatch.setattr(policy, "_REQUIRE_APPROVAL", frozenset({"notify"}))
    token = run_source.set("user")
    called = {"n": 0}

    def boom(**kwargs):
        called["n"] += 1
        return "sent"

    try:
        status, result = gated_call("notify_user", boom, {"message": "hi", "intent": "inform"})
    finally:
        run_source.reset(token)
    assert status == "approval_pending"
    assert "requires approval" in result
    assert called["n"] == 0
    assert decide("notify_user").verdict == REQUIRE_APPROVAL
