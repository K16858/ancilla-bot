import threading
from pathlib import Path

from ancilla_bot.runtime import persona as persona_mod
from ancilla_bot.runtime.persona import (
    format_persona_overlay,
    get_active_persona,
    load_persona,
    memory_class_allowed,
    set_persona,
    tool_denied_by_persona,
)


def test_load_researcher(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    try:
        spec = load_persona("researcher")
        assert spec.name == "researcher"
        assert "literature-research" in spec.preferred_skills
        assert "bash" in spec.tools_deny
        assert set_persona("researcher").startswith("Persona set to researcher")
        assert (tmp_path / "active_persona.txt").read_text(encoding="utf-8").strip() == "researcher"
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
        set_persona("general")
        persona_mod.end_temporary_persona()


def test_persisted_persona_survives_reread(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    path = tmp_path / "active_persona.txt"
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(path))
    persona_mod.end_temporary_persona()
    assert set_persona("developer").startswith("Persona set to developer")
    persona_mod.end_temporary_persona()
    assert get_active_persona().name == "developer"
    path.write_text("researcher\n", encoding="utf-8")
    assert get_active_persona().name == "researcher"
    set_persona("general")


def test_researcher_blocks_semantic_memory_write(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    assert set_persona("researcher").startswith("Persona set to researcher")
    assert memory_class_allowed("semantic", write=False)
    assert not memory_class_allowed("semantic", write=True)
    assert not memory_class_allowed("working", write=True)
    set_persona("general")
    assert memory_class_allowed("semantic", write=True)
