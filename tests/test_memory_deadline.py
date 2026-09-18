from datetime import datetime, timedelta

from ancilla_bot.memory.store import memories_to_personal_model


def test_goal_expires_at_becomes_deadline_within_days():
    expires = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    model = memories_to_personal_model(
        [{"kind": "goal", "subject": "short", "content": "ship", "expires_at": expires}]
    )
    goals = model["goals"]["short_term"]
    assert goals[0]["goal"] == "ship"
    assert goals[0]["deadline_within_days"] == 2
