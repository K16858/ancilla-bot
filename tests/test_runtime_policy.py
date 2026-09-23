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


def test_bash_denied_by_researcher_persona(monkeypatch, tmp_path):
    from ancilla_bot.runtime import persona as persona_mod
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    token = run_source.set("user")
    try:
        assert persona_mod.set_persona("researcher").startswith("Persona set to researcher")
        assert decide("bash").verdict == DENY
        assert decide("web_search").verdict == ALLOW
        assert decide("set_persona").verdict == ALLOW
    finally:
        persona_mod.set_persona("general")
        persona_mod.end_temporary_persona()
        run_source.reset(token)


def test_persona_require_approval(tmp_path, monkeypatch):
    from ancilla_bot.runtime import persona as persona_mod
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    personas = tmp_path / "personas"
    (personas / "cautious").mkdir(parents=True)
    (personas / "general").mkdir(parents=True)
    (personas / "general" / "persona.yaml").write_text("name: general\n", encoding="utf-8")
    (personas / "cautious" / "persona.yaml").write_text(
        "name: cautious\ntools:\n  require_approval:\n    - notify_user\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(personas))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    token = run_source.set("user")
    try:
        assert persona_mod.set_persona("cautious").startswith("Persona set to cautious")
        assert decide("notify_user").verdict == REQUIRE_APPROVAL
        assert decide("web_search").verdict == ALLOW
    finally:
        persona_mod.set_persona("general")
        persona_mod.end_temporary_persona()
        run_source.reset(token)
        monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))


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


def test_external_write_requires_approval_interactive():
    from ancilla_bot.runtime import capability as capability_mod
    from ancilla_bot.tools import registry as registry_mod

    capability_mod.set_mcp_risk("demo__write", "external_write")
    registry_mod.TOOL_REGISTRY["demo__write"] = lambda **kwargs: "ok"
    token = run_source.set("user")
    try:
        assert decide("demo__write").verdict == REQUIRE_APPROVAL
        assert decide("write_file").verdict == ALLOW
    finally:
        run_source.reset(token)
        registry_mod.TOOL_REGISTRY.pop("demo__write", None)
        capability_mod.clear_mcp_risks()


def test_external_read_allowed_when_autonomous():
    from ancilla_bot.runtime import capability as capability_mod
    from ancilla_bot.tools import registry as registry_mod

    capability_mod.set_mcp_risk("demo__search", "external_read")
    registry_mod.TOOL_REGISTRY["demo__search"] = lambda **kwargs: "ok"
    registry_mod.TOOL_REGISTRY["demo__unknown"] = lambda **kwargs: "ok"
    token = run_source.set("heartbeat")
    try:
        assert decide("demo__search").verdict == ALLOW
        assert decide("demo__unknown").verdict == DENY
    finally:
        run_source.reset(token)
        registry_mod.TOOL_REGISTRY.pop("demo__search", None)
        registry_mod.TOOL_REGISTRY.pop("demo__unknown", None)
        capability_mod.clear_mcp_risks()
