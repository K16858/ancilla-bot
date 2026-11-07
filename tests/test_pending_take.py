from pathlib import Path

from ancilla_bot.notifications.pending_take import requeue_pending_jsonl_lines, take_pending_jsonl_lines


def test_take_empties_queue_and_skips_blank_lines(tmp_path: Path):
    pending = tmp_path / "pending.jsonl"
    pending.write_text('{"a":1}\n\n  {"b":2}  \n', encoding="utf-8")
    assert take_pending_jsonl_lines(pending) == ['{"a":1}', '{"b":2}']
    assert not pending.exists()
    assert list(tmp_path.iterdir()) == []
    assert take_pending_jsonl_lines(pending) == []


def test_requeue_appends_after_new_arrivals(tmp_path: Path):
    pending = tmp_path / "q" / "pending.jsonl"
    requeue_pending_jsonl_lines([], pending)
    assert not pending.exists()
    pending.parent.mkdir()
    pending.write_text('{"new":1}\n', encoding="utf-8")
    requeue_pending_jsonl_lines(['{"old":1}', "  "], pending)
    assert take_pending_jsonl_lines(pending) == ['{"new":1}', '{"old":1}']
