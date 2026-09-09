from pathlib import Path

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.runtime.mode import active_mode, format_mode_overlay, set_mode


def test_set_mode_research(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_MODES_DIR", str(Path(__file__).resolve().parents[1] / "modes"))
    token = active_mode.set("general")
    try:
        assert set_mode("research").startswith("Mode set to research")
        overlay = format_mode_overlay()
        assert "Active mode: research" in overlay
        assert "literature-research" in overlay
        assert set_mode("nope").startswith("Error:")
    finally:
        active_mode.reset(token)


def test_composer_includes_mode_overlay(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_MODES_DIR", str(root / "modes"))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    token = active_mode.set("coding")
    try:
        prompt = build_core_memory("- get_time: now")
        assert "Active mode: coding" in prompt
        assert "Ancilla" in prompt
    finally:
        active_mode.reset(token)
