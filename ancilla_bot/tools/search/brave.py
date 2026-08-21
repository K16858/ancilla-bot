"""Brave Search プロバイダ。"""

import os

import httpx
from dotenv import load_dotenv
from loguru import logger

from ancilla_bot.tools.search.base import SearchHit

load_dotenv()

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT = float(os.getenv("BRAVE_TIMEOUT", "10"))


class BraveProvider:
    name = "brave"

    def __init__(self, *, api_key: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("BRAVE_API_KEY", "")
        self._timeout = timeout

    def available(self) -> bool:
        return bool(self._api_key)

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        if not self._api_key:
            raise RuntimeError("BRAVE_API_KEY が設定されていません。")
        logger.debug("brave query={} max_results={}", query, max_results)
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key,
        }
        params = {"q": query, "count": max_results}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(BRAVE_URL, params=params, headers=headers)
                resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("brave http error: {}", e)
            raise RuntimeError(f"Brave 検索に失敗しました: {e}") from e

        data = resp.json()
        web = data.get("web") or {}
        results = web.get("results") or []
        hits: list[SearchHit] = []
        for r in results[:max_results]:
            hits.append(
                SearchHit(
                    title=r.get("title") or "(no title)",
                    url=r.get("url") or "",
                    content=(r.get("description") or "").strip(),
                )
            )
        return hits
