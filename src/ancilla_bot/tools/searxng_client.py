"""
SearXNG 検索クライアント
"""

import json
import os

import httpx
from dotenv import load_dotenv
from loguru import logger

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


def search(
    query: str,
    max_results: int = 5,
    *,
    base_url: str = DEFAULT_URL,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """
    SearXNG で Web 検索を行い、結果を簡潔な文字列で返す。

    Args:
        query: 検索語
        max_results: 返す件数（デフォルト 5）
        base_url: エンドポイント（省略時は .env から）
        timeout: タイムアウト秒

    Returns:
        成功時: 各件を "title | url | content" の形式で改行区切りにした文字列
        失敗時: "Error: <メッセージ>"
        結果なし: "検索結果がありませんでした。"
    """
    url = f"{base_url.rstrip('/')}/search"
    params = {"q": query, "format": "json"}
    auth, headers = _get_auth_and_headers()
    logger.debug("searxng query={} max_results={}", query, max_results)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, params=params, auth=auth, headers=headers)
            resp.raise_for_status()
    except httpx.ConnectError as e:
        logger.warning("searxng connect error: {}", e)
        return f"Error: SearXNG に接続できません: {e}"
    except httpx.HTTPStatusError as e:
        logger.warning("searxng http error: {}", e.response.status_code)
        if e.response.status_code == 403:
            return "Error: SearXNG が JSON 形式を返しません。"
        return f"Error: SearXNG が {e.response.status_code} を返しました。"

    try:
        data = resp.json()
    except json.JSONDecodeError:
        logger.warning("searxng parse error")
        return "Error: 検索結果の解析に失敗しました。"

    results = data.get("results") or []
    logger.debug("searxng results={}", len(results))
    if not results:
        return "検索結果がありませんでした。"

    lines: list[str] = []
    for r in results[:max_results]:
        title = r.get("title", "(no title)")
        url_val = r.get("url", "(no url)")
        content = (r.get("content") or "").strip()
        lines.append(f"{title} | {url_val} | {content}")
    return "\n".join(lines)
