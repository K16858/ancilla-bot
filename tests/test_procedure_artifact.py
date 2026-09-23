import json
from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.tools.registry import search_memory


def _db(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")


def test_procedures_append_only(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    out = db.manage_state(
        "procedures",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "ancilla",
            "name": "deploy_docker_service",
            "steps": "check host\ncompose\ndeploy\nhealth",
        },
    )
    assert out.startswith("Inserted")
    row_id = json.loads(
        db.manage_state(
            "procedures",
            "select",
            {"scope_type": "project", "scope_id": "ancilla", "name": "deploy_docker_service"},
        )
    )[0]["id"]
    assert db.manage_state(
        "procedures",
        "update",
        {"id": row_id, "steps": "changed"},
    ).startswith("Error:")
    assert db.manage_state("procedures", "delete", {"id": row_id}).startswith(
        "Error: procedures is append-only."
    )
    found = search_memory(
        "deploy health",
        memory_class="procedural",
        scope_type="project",
        scope_id="ancilla",
    )
    assert "health" in found


def test_artifacts_append_only(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    out = db.manage_state(
        "artifacts",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "uav",
            "name": "UAV研究設計",
            "uri": "obsidian://Research/UAV/design.md",
            "summary": "UAV研究の設計資料",
        },
    )
    assert out.startswith("Inserted")
    assert db.manage_state(
        "artifacts",
        "update",
        {"id": 1, "summary": "x"},
    ).startswith("Error:")
    assert db.manage_state("artifacts", "delete", {"id": 1}).startswith(
        "Error: artifacts is append-only."
    )
    found = search_memory(
        "UAV 設計",
        memory_class="artifact",
        scope_type="project",
        scope_id="uav",
    )
    assert "設計資料" in found


def test_same_name_insert_supersedes_previous(tmp_path: Path, monkeypatch):
    _db(tmp_path, monkeypatch)
    db.manage_state(
        "procedures",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "ancilla",
            "name": "deploy",
            "steps": "v1",
        },
    )
    db.manage_state(
        "procedures",
        "insert",
        {
            "scope_type": "project",
            "scope_id": "ancilla",
            "name": "deploy",
            "steps": "v2",
        },
    )
    rows = json.loads(
        db.manage_state(
            "procedures",
            "select",
            {"scope_type": "project", "scope_id": "ancilla", "name": "deploy", "limit": 10},
        )
    )
    assert len(rows) == 1
    assert rows[0]["steps"] == "v2"
    assert rows[0]["lifecycle"] == "active"
    assert rows[0]["supersedes"] is not None
    found = search_memory(
        "deploy",
        memory_class="procedural",
        scope_type="project",
        scope_id="ancilla",
    )
    assert "v2" in found
    assert "v1" not in found
