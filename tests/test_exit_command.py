from ancilla_bot.core.agent_loop import is_exit_command


def test_exit_commands():
    assert is_exit_command("exit")
    assert is_exit_command("  QUIT  ")
    assert is_exit_command(":q")
    assert is_exit_command("/bye")
    assert not is_exit_command("hello")
