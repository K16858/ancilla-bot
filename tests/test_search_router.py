import pytest

from ancilla_bot.tools.search import router
from ancilla_bot.tools.search.base import SearchHit


class Fake:
    def __init__(self, name, *, available=True, hits=None, error=None):
        self.name = name
        self._available = available
        self._hits = hits or []
        self._error = error
        self.calls = 0

    def available(self):
        return self._available

    def search(self, query, max_results=5):
        self.calls += 1
        if self._error:
            raise RuntimeError(self._error)
        return self._hits


HIT = [SearchHit(title="T", url="https://example.com", content="c")]


@pytest.fixture
def providers(monkeypatch):
    fakes = {
        "brave": Fake("brave", available=False),
        "tavily": Fake("tavily"),
        "searxng": Fake("searxng"),
        "ddgs": Fake("ddgs", hits=HIT),
    }
    monkeypatch.setattr(router, "_all_providers", lambda: fakes)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    return fakes


def _names():
    return [p.name for p in router._build_chain()]


def test_chain_skips_unavailable_and_ends_with_ddgs(providers):
    assert _names() == ["tavily", "searxng", "ddgs"]


def test_main_provider_goes_first(providers, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "SearXNG")
    assert _names() == ["searxng", "tavily", "ddgs"]


def test_main_ddgs_is_not_duplicated(providers, monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "ddgs")
    assert _names() == ["ddgs", "tavily", "searxng"]


@pytest.mark.parametrize("main", ["brave", "bogus"])
def test_unavailable_or_unknown_main_falls_back_to_default_order(providers, monkeypatch, main):
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", main)
    assert _names() == ["tavily", "searxng", "ddgs"]


def test_search_falls_through_empty_and_failing_providers(providers):
    providers["tavily"]._error = "quota"
    out = router.search("q")
    assert "https://example.com" in out
    assert [providers[n].calls for n in ("tavily", "searxng", "ddgs")] == [1, 1, 1]


def test_search_reports_every_failure(providers):
    providers["ddgs"]._hits = []
    providers["tavily"]._error = "quota"
    out = router.search("q")
    assert out.startswith("Error")
    assert "tavily: quota" in out and "searxng: empty" in out and "ddgs: empty" in out
