"""
fetch_page: 指定 URL の Web ページを取得し、HTML を除去した本文を返す。
設計: docs/notes/fetch_page_design.md
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

URL_MAX_LEN = 2048
DEFAULT_TIMEOUT = float(os.getenv("FETCH_PAGE_TIMEOUT", "15"))
DEFAULT_MAX_BYTES = int(os.getenv("FETCH_PAGE_MAX_BYTES", "1000000"))
DEFAULT_MAX_CHARS = int(os.getenv("FETCH_PAGE_MAX_CHARS", "8000"))
USER_AGENT = "AncillaBot/1.0 fetch_page"


def _is_forbidden_host(host: str) -> bool:
    """localhost / 127.0.0.1 / プライベートアドレス / ::1 を拒否。"""
    if not host:
        return True
    host_lower = host.lower().strip()
    if host_lower in ("localhost", "localhost.", "0.0.0.0"):
        return True
    if host_lower.startswith("127.") or host_lower == "::1" or host_lower.startswith("[::1]"):
        return True
    # IPv6 [::1] など
    if host_lower.startswith("["):
        inner = host_lower[1:].split("]")[0]
        if inner == "::1" or inner == "::":
            return True
    # プライベート IPv4: 10.x, 172.16-31.x, 192.168.x
    parts = host.split(".")
    if len(parts) == 4:
        try:
            a, b, c, d = (int(x) for x in parts)
            if a == 10:
                return True
            if a == 172 and 16 <= b <= 31:
                return True
            if a == 192 and b == 168:
                return True
        except ValueError:
            pass
    return False


def _validate_url(url: str) -> str | None:
    """
    許可なら正規化済み URL（前後空白除去）、拒否なら None。
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if len(url) > URL_MAX_LEN:
        logger.debug("fetch_page: URL too long len={}", len(url))
        return None
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        logger.debug("fetch_page: scheme not allowed scheme={}", scheme)
        return None
    host = (parsed.hostname or "").strip()
    if _is_forbidden_host(host):
        logger.debug("fetch_page: forbidden host host={}", host)
        return None
    return url


def _fetch_bytes(
    url: str,
    timeout: float,
    max_bytes: int,
) -> tuple[bytes, str | None, str | None]:
    """
    GET で取得。サイズ超過時は (b"", "Error: ...", None) の形で返す。
    成功時は (body, None, content_type)。HTTP エラー時は (b"", "Error: ...", None)。
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            with client.stream("GET", url, headers=headers) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("content-type")
                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes(chunk_size=65536):
                    total += len(chunk)
                    if total > max_bytes:
                        return (b"", f"Error: ページが大きすぎます（上限 {max_bytes} バイト）。", None)
                    chunks.append(chunk)
                body = b"".join(chunks)
                return (body, None, content_type)
    except httpx.ConnectError as e:
        logger.debug("fetch_page connect error: {}", e)
        return (b"", "Error: 接続できませんでした（タイムアウトまたはネットワークエラー）。", None)
    except httpx.TimeoutException as e:
        logger.debug("fetch_page timeout: {}", e)
        return (b"", "Error: 接続できませんでした（タイムアウトまたはネットワークエラー）。", None)
    except httpx.HTTPStatusError as e:
        code = e.response.status_code if e.response else 0
        logger.debug("fetch_page http error: {}", code)
        return (b"", f"Error: HTTP {code} が返りました。", None)


def _decode(body: bytes, content_type_header: str | None) -> str | None:
    """
    Content-Type の charset → HTML の meta charset → UTF-8 仮定 → cp1252 フォールバック。
    失敗時は None。
    """
    if not body:
        return ""

    # Content-Type から charset を取得
    charset = None
    if content_type_header:
        for part in content_type_header.split(";"):
            part = part.strip().lower()
            if part.startswith("charset="):
                charset = part.split("=", 1)[1].strip().strip('"\'')
                break

    # HTML の meta charset（charset が未指定の場合）
    if not charset:
        head = body[:8192].decode("utf-8", errors="ignore")
        m = re.search(r'<meta[^>]+charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', head, re.I)
        if m:
            charset = m.group(1).strip()

    for enc in (charset or "utf-8", "utf-8", "cp1252"):
        if not enc:
            continue
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return None


class _TextExtractor(HTMLParser):
    """script/style をスキップし、それ以外のテキストを連結する。"""

    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data: str) -> None:
        if self.skip == 0 and data:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    """タグ除去・script/style 中身削除・空白正規化。"""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return ""
    text = " ".join(parser.parts)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_page(url: str, max_chars: int | None = None, **kwargs: Any) -> str:
    """
    指定 URL のページを取得し、HTML を除去した本文を返す。
    失敗時は "Error: ..." を返す。
    """
    _ = kwargs
    try:
        logger.debug("fetch_page url={}", url[:80] + "..." if len(url) > 80 else url)

        validated = _validate_url(url)
        if validated is None:
            if len((url or "").strip()) > URL_MAX_LEN:
                return "Error: URL が長すぎます。"
            scheme = urlparse((url or "").strip()).scheme.lower() if url else ""
            if scheme and scheme not in ("http", "https"):
                return "Error: URL は http または https のみ対応しています。"
            return "Error: その URL は許可されていません。"

        url = validated
        limit = max_chars if max_chars is not None else DEFAULT_MAX_CHARS
        limit = max(1, min(limit, 100_000))

        body, err, content_type = _fetch_bytes(url, DEFAULT_TIMEOUT, DEFAULT_MAX_BYTES)
        if err:
            return err

        decoded = _decode(body, content_type)
        if decoded is None:
            return "Error: ページの文字エンコーディングを判定できませんでした。"

        text = _html_to_text(decoded)
        if len(text) > limit:
            text = text[:limit] + "…"
        return text
    except Exception as e:
        logger.warning("fetch_page unexpected error: {}", e)
        return "Error: 取得に失敗しました。"
