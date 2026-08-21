"""SearXNG 検索プロバイダ。"""

import json
import os

import httpx
from dotenv import load_dotenv
from loguru import logger

from ancilla_bot.tools.search.base import SearchHit

load_dotenv()

DEFAULT_URL = os.getenv("SEARXNG_URL") or os.getenv("SEARXNG_BASE_URL", "http://localhost:8080")
DEFAULT_TIMEOUT = float(os.getenv("SEARXNG_TIMEOUT", "10"))


def _get_auth_and_headers() -> tuple[tuple[str, str] | None, dict[str, str]]:
    auth: tuple[str, str] | None = None
    headers: dict[str, str] = {}
    if os.getenv("SEARXNG_TOKEN"):
        headers["Authorization"] = f"Bearer {os.getenv('SEARXNG_TOKEN')}"
    elif os.getenv("SEARXNG_USER") and os.getenv("SEARXNG_PASSWORD"):
        auth = (os.getenv("SEARXNG_USER", ""), os.getenv("SEARXNG_PASSWORD", ""))
    return auth, headers


class SearXNGProvider:
    name = "searxng"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout

    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        url = f"{self._base_url.rstrip('/')}/search"
        params = {"q": query, "format": "json"}
        auth, headers = _get_auth_and_headers()
        logger.debug("searxng query={} max_results={}", query, max_results)

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.get(url, params=params, auth=auth, headers=headers)
                resp.raise_for_status()
        except httpx.ConnectError as e:
            logger.warning("searxng connect error: {}", e)
            raise RuntimeError(f"SearXNG に接続できません: {e}") from e
        except httpx.HTTPStatusError as e:
            logger.warning("searxng http error: {}", e.response.status_code)
            if e.response.status_code == 403:
                raise RuntimeError("SearXNG が JSON 形式を返しません。") from e
            raise RuntimeError(f"SearXNG が {e.response.status_code} を返しました。") from e

        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            logger.warning("searxng parse error")
            raise RuntimeError("検索結果の解析に失敗しました。") from e

        results = data.get("results") or []
        infoboxes = data.get("infoboxes") or []
        answers = data.get("answers") or []
        unresponsive = data.get("unresponsive_engines") or []
        logger.debug(
            "searxng results={} infoboxes={} answers={} unresponsive={}",
            len(results),
            len(infoboxes),
            len(answers),
            unresponsive,
        )
        if not results and not infoboxes and not answers:
            if unresponsive:
                detail = ", ".join(
                    f"{e[0]}:{e[1]}" if isinstance(e, (list, tuple)) and len(e) >= 2 else str(e)
                    for e in unresponsive
                )
                logger.warning("searxng no results; unresponsive engines: {}", detail)
                raise RuntimeError(f"検索結果がありませんでした。（エンジン障害: {detail}）")
            return []

        hits: list[SearchHit] = []
        for r in results[:max_results]:
            hits.append(
                SearchHit(
                    title=r.get("title", "(no title)"),
                    url=r.get("url", ""),
                    content=(r.get("content") or "").strip(),
                )
            )
        for box in infoboxes:
            hits.append(
                SearchHit(
                    title=box.get("infobox") or box.get("id") or "(infobox)",
                    url=box.get("id") or "",
                    content=(box.get("content") or "").strip(),
                )
            )
        for ans in answers:
            text = ans if isinstance(ans, str) else str(ans.get("answer") or ans)
            hits.append(SearchHit(title="answer", url="", content=text.strip()))
        return hits
