from pathlib import Path

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.runtime import persona as persona_mod
from ancilla_bot.runtime.persona import get_active_persona, set_persona
from ancilla_bot.runtime.self_model import format_runtime_self_model


def test_self_model_has_persona_not_gpu():
    text = format_runtime_self_model()
    assert "active_persona:" in text
    assert "capabilities:" in text
    assert "gpu" not in text.lower()


def test_character_stable_across_personas(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    prev = get_active_persona().name
    try:
        assert set_persona("general").startswith("Persona set to general")
        general = build_core_memory("- get_time: now")
        assert set_persona("researcher").startswith("Persona set to researcher")
        research = build_core_memory("- get_time: now")
    finally:
        persona_mod._persona_name = prev
    assert "Precision Support AI Maid" in general
    assert "Precision Support AI Maid" in research
    assert "ご主人様" in general and "ご主人様" in research
    assert "Active persona: general" in general
    assert "Active persona: researcher" in research
    assert "Runtime self model" in research
