import pytest

from ancilla_bot.cli.health import check_bind_hosts


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost"])
def test_loopback_allowed(monkeypatch, host):
    monkeypatch.delenv("ANCILLA_INSECURE_BIND", raising=False)
    check_bind_hosts({"API": host, "WS": "127.0.0.1"})


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "example.com"])
def test_non_loopback_rejected(monkeypatch, host):
    monkeypatch.delenv("ANCILLA_INSECURE_BIND", raising=False)
    with pytest.raises(SystemExit):
        check_bind_hosts({"API": "127.0.0.1", "MCP_HTTP": host})


def test_non_loopback_allowed_with_env(monkeypatch):
    monkeypatch.setenv("ANCILLA_INSECURE_BIND", "1")
    check_bind_hosts({"WS": "0.0.0.0"})
