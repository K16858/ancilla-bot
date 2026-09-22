from pathlib import Path

from ancilla_bot.cli.commands.persona import cmd_persona


def test_persona_cli_list_show_use(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))

    class NS:
        persona_command = "list"
        name = ""

    assert cmd_persona(NS()) == 0
    NS.persona_command = "use"
    NS.name = "researcher"
    assert cmd_persona(NS()) == 0
    assert (tmp_path / "active_persona.txt").read_text(encoding="utf-8").strip() == "researcher"
    NS.persona_command = "show"
    NS.name = ""
    assert cmd_persona(NS()) == 0
    NS.persona_command = "use"
    NS.name = "general"
    assert cmd_persona(NS()) == 0
