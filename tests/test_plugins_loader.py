from ancilla_bot.plugins.loader import load_plugins


def test_empty_plugins_env(monkeypatch):
    monkeypatch.setenv("ANCILLA_PLUGINS", "")
    assert load_plugins() == []


def test_csv_loads_known_and_ignores_unknown(monkeypatch):
    monkeypatch.setenv("ANCILLA_PLUGINS", "research, unknown, learning")
    names = [p.name for p in load_plugins()]
    assert names == ["research", "learning"]
