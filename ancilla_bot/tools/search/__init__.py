"""Web 検索プロバイダ。"""

from ancilla_bot.tools.search.base import SearchHit, SearchProvider
from ancilla_bot.tools.search.format import format_hits
from ancilla_bot.tools.search.searxng import SearXNGProvider

__all__ = ["SearchHit", "SearchProvider", "SearXNGProvider", "format_hits", "search"]


def search(query: str, max_results: int = 5) -> str:
    """暫定: SearXNG のみ。ルーター接続後に置き換える。"""
    try:
        hits = SearXNGProvider().search(query, max_results)
    except RuntimeError as e:
        return f"Error: {e}"
    return format_hits(hits)
