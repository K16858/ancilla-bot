from pathlib import Path

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.runtime.mode import get_active_mode, set_mode
from ancilla_bot.runtime.self_model import format_runtime_self_model


def test_self_model_has_mode_not_gpu():
    text = format_runtime_self_model()
    assert "active_mode:" in text
    assert "capabilities:" in text
    assert "gpu" not in text.lower()


def test_persona_stable_across_modes(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    monkeypatch.setenv("ANCILLA_MODES_DIR", str(root / "modes"))
    prev = get_active_mode().name
    try:
        assert set_mode("general").startswith("Mode set to general")
        general = build_core_memory("- get_time: now")
        assert set_mode("research").startswith("Mode set to research")
        research = build_core_memory("- get_time: now")
    finally:
        set_mode(prev)
    assert "Precision Support AI Maid" in general
    assert "Precision Support AI Maid" in research
    assert "ご主人様" in general and "ご主人様" in research
    assert "Active mode: general" in general
    assert "Active mode: research" in research
    assert "Runtime self model" in research
