from datetime import datetime, timedelta

from ancilla_bot.proactive import can_interrupt, note_interrupt
from ancilla_bot.proactive.engine import ProactiveAction
from ancilla_bot.proactive import throttle


def _action() -> ProactiveAction:
    return ProactiveAction(type="notify", content="hi", priority=1, trigger="gap")


def test_can_interrupt_does_not_consume_slot(monkeypatch):
    monkeypatch.setattr(throttle, "MAX_PROACTIVE_PER_HOUR", 1)
    throttle._last_proactive_dt = None
    throttle._proactive_count_hour = 0
    throttle._proactive_hour_key = ""
    assert can_interrupt(_action(), None)
    assert can_interrupt(_action(), None)
    note_interrupt()
    assert not can_interrupt(_action(), None)


def test_note_interrupt_enforces_cooldown(monkeypatch):
    monkeypatch.setattr(throttle, "MAX_PROACTIVE_PER_HOUR", 2)
    throttle._last_proactive_dt = None
    throttle._proactive_count_hour = 0
    throttle._proactive_hour_key = ""
    note_interrupt()
    assert not can_interrupt(_action(), datetime.now() - timedelta(minutes=1))
    assert can_interrupt(_action(), datetime.now() - timedelta(minutes=31))
