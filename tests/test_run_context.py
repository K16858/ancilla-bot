from ancilla_bot.core.run_context import current_source, is_autonomous, run_source


def test_idle_reflection_maps_to_idle():
    token = run_source.set("idle_reflection")
    try:
        assert is_autonomous() is True
        assert current_source() == "idle"
    finally:
        run_source.reset(token)


def test_heartbeat_maps_to_scheduler():
    token = run_source.set("heartbeat")
    try:
        assert is_autonomous() is True
        assert current_source() == "scheduler"
    finally:
        run_source.reset(token)


def test_user_source():
    token = run_source.set("user")
    try:
        assert is_autonomous() is False
        assert current_source() == "user"
    finally:
        run_source.reset(token)
