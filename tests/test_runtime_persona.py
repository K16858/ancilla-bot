import threading
from pathlib import Path

from ancilla_bot.runtime import persona as persona_mod
from ancilla_bot.runtime.persona import (
    format_persona_overlay,
    get_active_persona,
    load_persona,
    set_persona,
    tool_denied_by_persona,
)


def test_load_researcher(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    prev = persona_mod._persona_name
    try:
        spec = load_persona("researcher")
        assert spec.name == "researcher"
        assert "literature-research" in spec.preferred_skills
        assert "bash" in spec.tools_deny
        assert set_persona("researcher").startswith("Persona set to researcher")
        overlay = format_persona_overlay()
        assert "Active persona: researcher" in overlay
        assert tool_denied_by_persona("bash")
        assert not tool_denied_by_persona("set_persona")
        seen: list[str] = []

        def read() -> None:
            seen.append(get_active_persona().name)

        thread = threading.Thread(target=read)
        thread.start()
        thread.join()
        assert seen == ["researcher"]
        assert set_persona("nope").startswith("Error:")
    finally:
        persona_mod._persona_name = prev
