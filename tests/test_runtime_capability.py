from ancilla_bot.runtime import capability as capability_mod
from ancilla_bot.runtime.capability import get_capability, list_capabilities, risk_for


def test_builtin_capabilities_have_risks():
    names = {c.name: c.risk for c in list_capabilities()}
    assert names["get_time"] == "read_only"
    assert names["bash"] == "shell"
    assert names["write_file"] == "workspace_write"
    assert names["notify_user"] == "notify"
    assert names["mcp_list_resources"] == "external_read"
    assert get_capability("missing") is None
    assert risk_for("demo__tool") == "external_write"


def test_registered_mcp_read_only_risk():
    capability_mod.clear_mcp_risks()
    capability_mod.set_mcp_risk("drive__search", "external_read")
    try:
        assert risk_for("drive__search") == "external_read"
        assert risk_for("drive__write") == "external_write"
    finally:
        capability_mod.clear_mcp_risks()
