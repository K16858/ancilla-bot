from pathlib import Path

from ancilla_bot.skills.loader import list_skills, read_skill


def test_literature_research_skill(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(root / "skills"))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(root / "workspace"))
    skills = {s.name: s for s in list_skills()}
    spec = skills["literature-research"]
    assert spec.recommended_modes == ("research",)
    assert "web_search" in spec.requires_capabilities
    body = read_skill("literature-research")
    assert "search_arxiv" in body
    assert "Recommended modes: research" in body
