from pathlib import Path

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
        "recommended_modes:\n  - research\nrisk: read_only\n---\nBody.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(bundled))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    skill = list_skills()[0]
    assert skill.version == 2
    assert skill.requires_capabilities == ("web_search",)
    assert skill.recommended_modes == ("research",)
    assert skill.risk == "read_only"
    assert "Recommended modes: research" in read_skill("lit")


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
