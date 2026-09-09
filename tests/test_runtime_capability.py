from ancilla_bot.runtime.capability import get_capability, list_capabilities, risk_for


def test_builtin_capabilities_have_risks():
    names = {c.name: c.risk for c in list_capabilities()}
    assert names["get_time"] == "read_only"
    assert names["bash"] == "shell"
    assert names["write_file"] == "workspace_write"
    assert names["notify_user"] == "notify"
    assert get_capability("missing") is None
    assert risk_for("demo__tool") == "external_write"
