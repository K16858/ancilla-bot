from ancilla_bot.heartbeat import retry


def setup_function() -> None:
    retry._fails.clear()
    retry._retry_at.clear()


def test_timeout_poisons_after_max_fails() -> None:
    row = {"_table": "reminders", "id": 98}
    timeout = "応答の解析に失敗しました。もう一度試してください。"
    assert retry.is_permanent_failure(timeout) is False
    assert retry.record_failure([row], timeout) == []
    assert retry.record_failure([row], timeout) == []
    poisoned = retry.record_failure([row], timeout)
    assert [r["id"] for r in poisoned] == [98]
    assert retry.actionable([row]) == [row]


def test_empty_response_poisons_immediately() -> None:
    row = {"_table": "reminders", "id": 1}
    empty = "内部エラーが発生しました（空の応答）。少し待ってからもう一度試してください。"
    assert retry.is_permanent_failure(empty) is True
    poisoned = retry.record_failure([row], empty)
    assert [r["id"] for r in poisoned] == [1]


def test_backoff_hides_due_until_retry_at() -> None:
    row = {"_table": "reminders", "id": 2}
    timeout = "応答の解析に失敗しました。もう一度試してください。"
    retry.record_failure([row], timeout)
    assert retry.actionable([row]) == []
    retry._retry_at[retry.due_key(row)] = 0
    assert retry.actionable([row]) == [row]
