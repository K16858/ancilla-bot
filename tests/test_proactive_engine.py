from datetime import datetime

from ancilla_bot.proactive.engine import _eval_condition, evaluate


def test_eval_gap_condition():
    assert _eval_condition(
        "conversation_gap_seconds > 14400 AND is_active_hours",
        {"conversation_gap_seconds": 14401, "is_active_hours": True},
    )
    assert not _eval_condition(
        "conversation_gap_seconds > 14400 AND is_active_hours",
        {"conversation_gap_seconds": 14401, "is_active_hours": False},
    )


def test_evaluate_gap_rule_fires():
    snapshot = {
        "time": {"value": {"is_active_hours": True}},
        "conversation_gap": {"value": {"conversation_gap_seconds": 20000}},
    }
    rules = [
        {
            "id": "gap",
            "condition": "conversation_gap_seconds > 14400 AND is_active_hours",
            "action": "notify",
            "message_template": "check in {goal}",
        }
    ]
    model = {
        "goals": {"short_term": [{"goal": "ship", "deadline_within_days": 10}]},
        "patterns": {"interruption_tolerance": "high"},
    }
    action = evaluate(snapshot, model, rules, datetime(2026, 1, 1))
    assert action is not None
    assert action.content == "check in ship"
    assert action.priority == 3
    assert action.trigger == "gap"


def test_evaluate_no_match_returns_none():
    snapshot = {
        "time": {"value": {"is_active_hours": False}},
        "conversation_gap": {"value": {"conversation_gap_seconds": 10}},
    }
    rules = [
        {
            "id": "gap",
            "condition": "conversation_gap_seconds > 14400 AND is_active_hours",
            "message_template": "hi",
        }
    ]
    assert evaluate(snapshot, {}, rules, datetime(2026, 1, 1)) is None
