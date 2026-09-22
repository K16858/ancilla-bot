import threading
from pathlib import Path

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.runtime.mode import get_active_mode, set_mode, format_mode_overlay


def test_set_mode_research(monkeypatch):
    monkeypatch.setenv("ANCILLA_MODES_DIR", str(Path(__file__).resolve().parents[1] / "modes"))
    prev = get_active_mode().name
    try:
        assert set_mode("research").startswith("Mode set to research")
        overlay = format_mode_overlay()
        assert "Active mode: research" in overlay
        assert "literature-research" in overlay
        assert set_mode("nope").startswith("Error:")
        seen: list[str] = []

        def read() -> None:
            seen.append(get_active_mode().name)

        thread = threading.Thread(target=read)
        thread.start()
        thread.join()
        assert seen == ["research"]
    finally:
        set_mode(prev)


def test_composer_includes_mode_overlay(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_MODES_DIR", str(root / "modes"))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    prev = get_active_mode().name
    try:
        assert set_mode("coding").startswith("Mode set to coding")
        prompt = build_core_memory("- get_time: now")
        assert "Active mode: coding" in prompt
        assert "Ancilla" in prompt
    finally:
        set_mode(prev)
