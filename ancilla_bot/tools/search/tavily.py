"""Tavily 検索プロバイダ。"""

import os

import httpx
from dotenv import load_dotenv
from loguru import logger

from ancilla_bot.tools.search.base import SearchHit

load_dotenv()

TAVILY_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT = float(os.getenv("TAVILY_TIMEOUT", "10"))


class TavilyProvider:
    name = "tavily"

    def __init__(self, *, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("TAVILY_API_KEY", "")
        self._timeout = timeout

    def available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self._api_key:
            raise RuntimeError("TAVILY_API_KEY が設定されていません。")
        logger.debug("tavily query={} max_results={}", query, max_results)
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(TAVILY_URL, json=payload)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("tavily http error: {}", e)
            raise RuntimeError(f"Tavily 検索に失敗しました: {e}") from e

        data = resp.json()
        results = data.get("results") or []
        hits: list[SearchHit] = []
        for r in results[:max_results]:
            hits.append(
                SearchHit(
                    title=r.get("title") or "(no title)",
                    url=r.get("url") or "",
                    content=(r.get("content") or "").strip(),
                )
            )
        return hits
