from pathlib import Path

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.runtime import persona as persona_mod
from ancilla_bot.runtime.persona import set_persona
from ancilla_bot.runtime.self_model import format_runtime_self_model


def test_self_model_has_persona_not_gpu(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    set_persona("general")
    text = format_runtime_self_model()
    assert "active_persona:" in text
    assert "capabilities:" in text
    assert "resources: local only" in text
    assert "gpu" not in text.lower()


def test_character_stable_across_personas(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    try:
        assert set_persona("general").startswith("Persona set to general")
        general = build_core_memory("- get_time: now")
        assert set_persona("researcher").startswith("Persona set to researcher")
        research = build_core_memory("- get_time: now")
    finally:
        set_persona("general")
        persona_mod.end_temporary_persona()
    assert "Precision Support AI Maid" in general
    assert "Precision Support AI Maid" in research
    assert "ご主人様" in general and "ご主人様" in research
    assert "Active persona: general" in general
    assert "Active persona: researcher" in research
    assert "Runtime self model" in research
