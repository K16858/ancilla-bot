"""検索プロバイダの登録とフォールバック連鎖。"""

import os

from dotenv import load_dotenv
from loguru import logger

from ancilla_bot.tools.search.base import SearchHit, SearchProvider
from ancilla_bot.tools.search.brave import BraveProvider
from ancilla_bot.tools.search.ddgs import DDGSProvider
from ancilla_bot.tools.search.format import format_hits
from ancilla_bot.tools.search.searxng import SearXNGProvider
from ancilla_bot.tools.search.tavily import TavilyProvider

load_dotenv()

# 登録順（フォールバック時の試行順。ddgs は最終専用）
_PROVIDER_ORDER = ("brave", "tavily", "searxng")


def _all_providers() -> dict[str, SearchProvider]:
    return {
        "brave": BraveProvider(),
        "tavily": TavilyProvider(),
        "searxng": SearXNGProvider(),
        "ddgs": DDGSProvider(),
    }


def _build_chain() -> list[SearchProvider]:
    providers = _all_providers()
    main_name = (os.getenv("WEB_SEARCH_PROVIDER") or "").strip().lower()
    if main_name and main_name not in providers:
        logger.warning("unknown WEB_SEARCH_PROVIDER={!r}, ignoring", main_name)
        main_name = ""

    chain: list[SearchProvider] = []
    if main_name:
        main = providers[main_name]
        if main.available():
            chain.append(main)
        else:
            logger.warning("main provider {} is not available, skipping", main_name)

    for name in _PROVIDER_ORDER:
        if name == main_name:
            continue
        p = providers[name]
        if p.available():
            chain.append(p)

    if main_name != "ddgs":
        chain.append(providers["ddgs"])
    elif not chain:
        chain.append(providers["ddgs"])

    return chain


def search(query: str, max_results: int = 5) -> str:
    chain = _build_chain()
    errors: list[str] = []
    for provider in chain:
        try:
            hits: list[SearchHit] = provider.search(query, max_results)
            if not hits:
                logger.warning("{} returned no results, trying next", provider.name)
                errors.append(f"{provider.name}: empty")
                continue
            logger.debug("web_search used provider={}", provider.name)
            return format_hits(hits)
        except Exception as e:
            logger.warning("{} failed: {}", provider.name, e)
            errors.append(f"{provider.name}: {e}")
    detail = "; ".join(errors) if errors else "no providers"
    return f"Error: すべての検索プロバイダが失敗しました（{detail}）"
