"""DDGS (Python ライブラリ) 検索プロバイダ。"""

from loguru import logger

from ancilla_bot.tools.search.base import SearchHit


class DDGSProvider:
    name = "ddgs"

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        from ddgs import DDGS

        logger.debug("ddgs query={} max_results={}", query, max_results)
        try:
            results = DDGS().text(query, max_results=max_results)
        except Exception as e:
            logger.warning("ddgs search error: {}", e)
            raise RuntimeError(f"DDGS 検索に失敗しました: {e}") from e

        hits: list[SearchHit] = []
        for r in results or []:
            hits.append(
                SearchHit(
                    title=r.get("title") or "(no title)",
                    url=r.get("href") or r.get("url") or "",
                    content=(r.get("body") or r.get("content") or "").strip(),
                )
            )
        return hits[:max_results]
