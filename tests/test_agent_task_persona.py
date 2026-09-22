from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.runtime import persona as persona_mod
from ancilla_bot.runtime.persona import (
    begin_temporary_persona,
    end_temporary_persona,
    get_active_persona,
    set_persona,
)


def test_agent_task_persona_and_temporary(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    persona_mod.end_temporary_persona()
    set_persona("general")
    msg = db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-01 00:00:00",
            "content": "research something",
            "persona": "researcher",
            "source": "heartbeat",
        },
    )
    assert msg.startswith("Inserted into agent_tasks")
    begin_temporary_persona("researcher")
    assert get_active_persona().name == "researcher"
    end_temporary_persona()
    assert get_active_persona().name == "general"
    bad = db.manage_state(
        "agent_tasks",
        "insert",
        {
            "scheduled_at": "2099-01-02 00:00:00",
            "content": "x",
            "persona": "nope",
            "source": "heartbeat",
        },
    )
    assert "unknown persona" in bad.lower()
    set_persona("general")
