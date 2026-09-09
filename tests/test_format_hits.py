from ancilla_bot.tools.search.base import SearchHit
from ancilla_bot.tools.search.format import format_hits


def test_empty_hits():
    assert format_hits([]) == "検索結果がありませんでした。"


def test_truncates_long_content():
    hit = SearchHit(title="T", url="http://x", content="a" * 301)
    out = format_hits([hit])
    assert out.startswith("[1] T\n")
    assert out.endswith("...")
    assert "a" * 300 in out


def test_no_truncation_when_unlimited():
    hit = SearchHit(title="T", url="http://x", content="a" * 301)
    out = format_hits([hit], content_max_chars=None)
    assert out.endswith("a" * 301)
    assert "..." not in out
