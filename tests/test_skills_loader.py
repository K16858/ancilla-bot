from pathlib import Path

from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.runtime import persona as persona_mod
from ancilla_bot.runtime.persona import get_active_persona, set_persona
from ancilla_bot.skills.loader import format_skills_catalog, list_skills, read_skill


def test_workspace_cannot_override_bundled(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "bundled"
    ws = tmp_path / "ws"
    (bundled / "alpha").mkdir(parents=True)
    (bundled / "shared").mkdir(parents=True)
    (ws / "skills" / "shared").mkdir(parents=True)
    (ws / "skills" / "beta").mkdir(parents=True)
    (bundled / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Bundled alpha.\n---\nAlpha body.\n",
        encoding="utf-8",
    )
    (bundled / "shared" / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Bundled shared.\n---\nBundled body.\n",
        encoding="utf-8",
    )
    (ws / "skills" / "shared" / "SKILL.md").write_text(
        "---\nname: shared\ndescription: Workspace shared.\n---\nWorkspace body.\n",
        encoding="utf-8",
    )
    (ws / "skills" / "beta" / "SKILL.md").write_text(
        "---\ndescription: Workspace beta.\n---\nBeta body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(bundled))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))

    names = [s.name for s in list_skills()]
    assert names == ["alpha", "beta", "shared"]
    assert read_skill("shared") == "Bundled body."
    assert read_skill("missing").startswith("Error:")
    catalog = format_skills_catalog()
    assert "alpha: Bundled alpha." in catalog
    assert "Bundled shared." in catalog


def test_skill_spec_frontmatter(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "bundled"
    (bundled / "lit").mkdir(parents=True)
    (bundled / "lit" / "SKILL.md").write_text(
        "---\nname: lit\nversion: 2\ndescription: Lit.\n"
        "requires:\n  capabilities:\n    - web_search\n"
        "recommended_personas:\n  - researcher\nrisk: read_only\n---\nBody.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(bundled))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    skill = list_skills()[0]
    assert skill.version == 2
    assert skill.requires_capabilities == ("web_search",)
    assert skill.recommended_personas == ("researcher",)
    assert skill.risk == "read_only"
    assert "Recommended personas: researcher" in read_skill("lit")


def test_workspace_unknown_capability_rejected(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    ws = tmp_path / "ws"
    (ws / "skills" / "evil").mkdir(parents=True)
    (ws / "skills" / "evil" / "SKILL.md").write_text(
        "---\nname: evil\ndescription: Nope.\n"
        "requires:\n  capabilities:\n    - not_a_cap\n---\nBody.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(bundled))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    assert list_skills() == []


def test_trial_workspace_skill_catalogued(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    ws = tmp_path / "ws"
    (ws / "skills" / "draft").mkdir(parents=True)
    (ws / "skills" / "draft" / "SKILL.md").write_text(
        "---\nname: draft\ndescription: Draft skill.\nstatus: trial\n"
        "requires:\n  capabilities:\n    - web_search\n---\nDraft body.\n",
        encoding="utf-8",
    )
    (ws / "skills" / "draft" / "SKILL.v1.md").write_text("old", encoding="utf-8")
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(bundled))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    skills = list_skills()
    assert len(skills) == 1
    assert skills[0].status == "trial"
    assert skills[0].version == 1
    catalog = format_skills_catalog()
    assert "draft [trial]" in catalog
    assert read_skill("draft") == "Draft body."


def test_preferred_skills_lead_catalog(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "bundled"
    (bundled / "alpha").mkdir(parents=True)
    (bundled / "zeta").mkdir(parents=True)
    (bundled / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: A.\n---\nA.\n",
        encoding="utf-8",
    )
    (bundled / "zeta" / "SKILL.md").write_text(
        "---\nname: zeta\ndescription: Z.\n---\nZ.\n",
        encoding="utf-8",
    )
    personas = tmp_path / "personas"
    (personas / "general").mkdir(parents=True)
    (personas / "focus").mkdir(parents=True)
    (personas / "general" / "persona.yaml").write_text("name: general\n", encoding="utf-8")
    (personas / "focus" / "persona.yaml").write_text(
        "name: focus\nskills:\n  preferred:\n    - zeta\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(bundled))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(personas))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    try:
        assert set_persona("focus").startswith("Persona set to focus")
        catalog = format_skills_catalog()
        assert catalog.index("- zeta:") < catalog.index("- alpha:")
    finally:
        set_persona("general")
        persona_mod.end_temporary_persona()


def test_composer_includes_persona_overlay(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_PERSONAS_DIR", str(root / "personas"))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    monkeypatch.setenv("ANCILLA_ACTIVE_PERSONA_PATH", str(tmp_path / "active_persona.txt"))
    persona_mod.end_temporary_persona()
    try:
        assert set_persona("developer").startswith("Persona set to developer")
        prompt = build_core_memory("- get_time: now")
        assert "Active persona: developer" in prompt
        assert "Ancilla" in prompt
    finally:
        set_persona("general")
        persona_mod.end_temporary_persona()
