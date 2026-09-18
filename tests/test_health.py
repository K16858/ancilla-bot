import pytest

from ancilla_bot.cli.health import core_url


@pytest.mark.parametrize(
    "host, expected",
    [
        ("0.0.0.0", "http://127.0.0.1:8765"),
        ("::", "http://127.0.0.1:8765"),
        ("127.0.0.1", "http://127.0.0.1:8765"),
        ("10.0.0.5", "http://10.0.0.5:8765"),
    ],
)
def test_core_url_skips_wildcard_bind_host(monkeypatch, host, expected):
    monkeypatch.delenv("ANCILLA_CORE_URL", raising=False)
    monkeypatch.setenv("ANCILLA_API_HOST", host)
    monkeypatch.setenv("ANCILLA_API_PORT", "8765")
    assert core_url() == expected


def test_core_url_prefers_explicit(monkeypatch):
    monkeypatch.setenv("ANCILLA_CORE_URL", "http://core.example:9000/")
    monkeypatch.setenv("ANCILLA_API_HOST", "0.0.0.0")
    assert core_url() == "http://core.example:9000"
