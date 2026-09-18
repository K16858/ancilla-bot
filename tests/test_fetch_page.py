from ancilla_bot.tools.fetch_page import _is_forbidden_host, fetch_page


def test_forbidden_literal_hosts():
    assert _is_forbidden_host("127.0.0.1")
    assert _is_forbidden_host("localhost")
    assert _is_forbidden_host("10.0.0.1")
    assert _is_forbidden_host("192.168.1.1")
    assert _is_forbidden_host("172.16.0.1")
    assert _is_forbidden_host("169.254.169.254")
    assert _is_forbidden_host("::1")
    assert _is_forbidden_host("[::1]")
    assert _is_forbidden_host("0.0.0.0")


def test_public_ipv4_allowed():
    assert not _is_forbidden_host("8.8.8.8")


def test_fetch_page_rejects_localhost():
    assert fetch_page("http://127.0.0.1/") == "Error: その URL は許可されていません。"
    assert fetch_page("http://localhost/") == "Error: その URL は許可されていません。"
