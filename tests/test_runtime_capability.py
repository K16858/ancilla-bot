from ancilla_bot.mcp.bridge import _effect_from_annotations
from ancilla_bot.runtime import capability as capability_mod
from ancilla_bot.runtime.capability import effect_for, get_capability, list_capabilities, scope_for


def test_builtin_capabilities_have_effects():
    names = {c.name: c.effect for c in list_capabilities()}
    scopes = {c.name: c.scope for c in list_capabilities()}
    assert names["get_time"] == "local_read"
    assert scopes["get_time"] == "os"
    assert names["bash"] == "privileged"
    assert scopes["bash"] == "os"
    assert names["write_file"] == "local_write"
    assert scopes["write_file"] == "workspace"
    assert names["trash_file"] == "destructive"
    assert names["notify_user"] == "local_write"
    assert names["web_search"] == "external_read"
    assert scopes["web_search"] == "web"
    assert names["search_memory"] == "local_read"
    assert scopes["search_memory"] == "memory"
    assert names["mcp_list_resources"] == "external_read"
    assert get_capability("missing") is None
    assert effect_for("demo__tool") == "external_write"
    assert scope_for("demo__tool") == "demo"


def test_registered_mcp_effect():
    capability_mod.clear_mcp_effects()
    capability_mod.set_mcp_effect("drive__search", "external_read", "drive")
    try:
        assert effect_for("drive__search") == "external_read"
        assert scope_for("drive__search") == "drive"
        assert effect_for("drive__write") == "external_write"
    finally:
        capability_mod.clear_mcp_effects()


def test_read_only_hint_is_external_read():
    class _Ann:
        destructive_hint = False
        read_only_hint = True

    class _Tool:
        annotations = _Ann()

    assert _effect_from_annotations(_Tool()) == "external_read"


def test_missing_annotations_are_external_write():
    class _Tool:
        annotations = None

    assert _effect_from_annotations(_Tool()) == "external_write"
