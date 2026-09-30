from ancilla_bot.core.agent_loop import compose_run_system


def test_compose_run_system_appends_relevant_memory(monkeypatch):
    seen = {}

    def fake_retrieve(query, context):
        seen["query"] = query
        seen["task_id"] = context.task_id
        seen["user_id"] = context.user_id
        return "## Relevant Memory\n\n### Working\ngoal: x"

    monkeypatch.setattr(
        "ancilla_bot.core.agent_loop.build_tools_system_prompt",
        lambda: "SYS",
    )
    monkeypatch.setattr("ancilla_bot.core.agent_loop.retrieve_context", fake_retrieve)
    text = compose_run_system("resume capability", task_key="cap-refactor", source="heartbeat")
    assert text == "SYS\n\n## Relevant Memory\n\n### Working\ngoal: x"
    assert seen == {
        "query": "resume capability",
        "task_id": "cap-refactor",
        "user_id": "default",
    }


def test_compose_run_system_skips_idle(monkeypatch):
    monkeypatch.setattr(
        "ancilla_bot.core.agent_loop.build_tools_system_prompt",
        lambda: "SYS",
    )

    def boom(query, context):
        raise AssertionError("router should not run")

    monkeypatch.setattr("ancilla_bot.core.agent_loop.retrieve_context", boom)
    assert compose_run_system("idle", task_key="cap", source="idle_reflection") == "SYS"
