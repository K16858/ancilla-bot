from ancilla_bot.memory.short_term import append_and_trim, estimate_chars


def test_append_and_trim_drops_oldest():
    history = [
        {"role": "user", "content": "aaaa"},
        {"role": "assistant", "content": "bbbb"},
    ]
    dropped = append_and_trim(
        history,
        [{"role": "user", "content": "cccc"}],
        max_chars=8,
    )
    assert dropped == [{"role": "user", "content": "aaaa"}]
    assert [m["content"] for m in history] == ["bbbb", "cccc"]
    assert estimate_chars(history) == 8
