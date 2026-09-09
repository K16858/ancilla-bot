from ancilla_bot.llm.context_window import history_chars_from_n_ctx


def test_non_positive_n_ctx_uses_default():
    assert history_chars_from_n_ctx(0) == 4000
    assert history_chars_from_n_ctx(-1) == 4000


def test_budget_is_half_ctx_times_chars_per_token():
    assert history_chars_from_n_ctx(4096) == 4096
