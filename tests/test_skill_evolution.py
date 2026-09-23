from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.skills import evolution as evo


def _ws_skill(tmp_path: Path, monkeypatch, *, status: str = "trial") -> Path:
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    ws = tmp_path / "ws"
    skill_dir = ws / "skills" / "draft"
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: draft\ndescription: Draft.\nversion: 1\nstatus: {status}\n---\n\nBody v1.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(tmp_path / "bundled"))
    (tmp_path / "bundled").mkdir()
    return path


def test_promote_requires_three_successes(tmp_path: Path, monkeypatch):
    path = _ws_skill(tmp_path, monkeypatch)
    assert evo.promote_skill("draft").startswith("Error: need 3")
    for i in range(3):
        db.record_skill_run(name="draft", version=1, run_id=f"r{i}", outcome="success")
    out = evo.promote_skill("draft")
    assert out.startswith("Promoted")
    text = path.read_text(encoding="utf-8")
    assert "status: active" in text
    assert db.latest_skill_promotion("draft") is not None


def test_promote_blocked_by_failure(tmp_path: Path, monkeypatch):
    _ws_skill(tmp_path, monkeypatch)
    db.record_skill_run(name="draft", version=1, run_id="a", outcome="success")
    db.record_skill_run(name="draft", version=1, run_id="b", outcome="failure")
    db.record_skill_run(name="draft", version=1, run_id="c", outcome="success")
    assert "failures" in evo.promote_skill("draft")


def test_rollback_restores_trial(tmp_path: Path, monkeypatch):
    path = _ws_skill(tmp_path, monkeypatch)
    for i in range(3):
        db.record_skill_run(name="draft", version=1, run_id=f"r{i}", outcome="success")
    evo.promote_skill("draft")
    path.write_text(path.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
    out = evo.rollback_skill("draft")
    assert out.startswith("Rolled back")
    text = path.read_text(encoding="utf-8")
    assert "status: trial" in text
    assert "Body v1." in text
    assert "extra" not in text


def test_flush_skill_runs_records_outcome(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    tokens = evo.reset_skill_run_tracking()
    try:
        evo.note_skill_loaded("draft", 1)
        evo.flush_skill_runs("run-ok", completed=True)
        evo.note_skill_loaded("draft", 1)
        evo.note_tool_failure()
        evo.flush_skill_runs("run-bad", completed=True)
    finally:
        evo.restore_skill_run_tracking(tokens)
    rows = db.list_skill_runs("draft", version=1)
    outcomes = {r["run_id"]: r["outcome"] for r in rows}
    assert outcomes["run-ok"] == "success"
    assert outcomes["run-bad"] == "failure"
