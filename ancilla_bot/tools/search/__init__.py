"""Web 検索プロバイダ。"""

from ancilla_bot.tools.search.base import SearchHit, SearchProvider
from ancilla_bot.tools.search.brave import BraveProvider
from ancilla_bot.tools.search.ddgs import DDGSProvider
from ancilla_bot.tools.search.format import format_hits
from ancilla_bot.tools.search.router import search
from ancilla_bot.tools.search.searxng import SearXNGProvider
from ancilla_bot.tools.search.tavily import TavilyProvider

__all__ = [
    "BraveProvider",
    "DDGSProvider",
    "SearchHit",
    "SearchProvider",
    "SearXNGProvider",
    "TavilyProvider",
    "format_hits",
    "search",
]
