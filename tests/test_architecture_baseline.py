from pathlib import Path

from ancilla_bot.heartbeat import db
from ancilla_bot.memory import core as memory_core
from ancilla_bot.memory.core import build_core_memory
from ancilla_bot.skills.loader import read_skill
from ancilla_bot.tools.registry import TOOL_REGISTRY
from ancilla_bot.tools.workspace_io import read_file, write_file

BUILTIN_TOOLS = {
    "get_time",
    "web_search",
    "fetch_page",
    "search_arxiv",
    "list_workspace",
    "edit_file_safe",
    "bash",
    "load_skill",
    "set_mode",
    "read_file",
    "write_file",
    "trash_file",
    "move_file",
    "workspace_inventory",
    "search_memory",
    "get_user_context",
    "update_user_goal",
    "manage_state",
    "notify_user",
    "finish",
    "end_edge_session",
    "use_edgedevice",
    "get_image",
    "get_audio",
    "mcp_list_resources",
    "mcp_read_resource",
    "mcp_list_prompts",
    "mcp_get_prompt",
}

ROOT = Path(__file__).resolve().parents[1]


def test_builtin_tool_registry_keys():
    assert BUILTIN_TOOLS.issubset(TOOL_REGISTRY.keys())


def test_core_memory_includes_character_agent_skills(monkeypatch):
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ROOT / "workspace"))
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(ROOT / "skills"))
    monkeypatch.setattr(memory_core, "DEFAULT_PROMPTS_DIR", ROOT / "data" / "prompts")
    prompt = build_core_memory("- get_time: now")
    assert "Ancilla" in prompt
    assert "Behavior" in prompt or "valid JSON" in prompt
    assert "bash" in prompt
    assert "## Available skills" in prompt


def test_tools_catalog_includes_set_mode(monkeypatch):
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ROOT / "workspace"))
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(ROOT / "skills"))
    monkeypatch.setattr(memory_core, "DEFAULT_PROMPTS_DIR", ROOT / "data" / "prompts")
    from ancilla_bot.tools.registry import build_tools_system_prompt

    prompt = build_tools_system_prompt()
    assert "set_mode" in prompt


def test_load_skill_bash(monkeypatch):
    monkeypatch.setenv("ANCILLA_SKILLS_DIR", str(ROOT / "skills"))
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ROOT / "workspace"))
    body = read_skill("bash")
    assert "workspace" in body.lower()
    assert not body.startswith("Error:")


def test_memories_insert_projects_user_md(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(db, "DEFAULT_CONVERSATION_DIR", tmp_path)
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    monkeypatch.setattr("ancilla_bot.memory.store.PERSONAL_MODEL_PATH", tmp_path / "model.yaml")
    result = db.manage_state(
        "memories",
        "insert",
        {"kind": "fact", "subject": "pet", "content": "cat"},
        trusted_user=True,
    )
    assert result.startswith("Inserted into memories")
    text = (ws / "USER.md").read_text(encoding="utf-8")
    assert "cat" in text


def test_workspace_rejects_outside_and_user_md(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("ANCILLA_WORKSPACE_DIR", str(ws))
    assert "workspace 以下のみ" in read_file("../secret.txt")
    assert "projection" in write_file("USER.md", "nope")


def test_search_arxiv_is_builtin():
    assert "search_arxiv" in TOOL_REGISTRY
