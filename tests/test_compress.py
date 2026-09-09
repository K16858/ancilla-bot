from ancilla_bot.memory.compress import get_oldest_block, should_compress


def test_should_compress_respects_ratio_and_zero_budget():
    history = [{"role": "user", "content": "x" * 80}]
    assert should_compress(history, 100) is True
    assert should_compress(history, 200) is False
    assert should_compress(history, 0) is False


def test_get_oldest_block_caps_at_history_length():
    history = [{"role": "user", "content": str(i)} for i in range(3)]
    assert get_oldest_block(history, 10) == history
    assert get_oldest_block(history, 2) == history[:2]
