"""ビルド済み WebUI（webui/dist）の静的配信。トークン不要（中身は API が守る）。"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote

from ancilla_bot.cli.paths import get_root

HINT = "webui をビルドしてください（cd webui && npm ci && npm run build）"


def dist_dir() -> Path:
    raw = (os.getenv("ANCILLA_WEBUI_DIR") or "").strip()
    return Path(raw).expanduser().resolve() if raw else get_root() / "webui" / "dist"


def resolve(path: str) -> tuple[int, str, bytes, str]:
    """/ui 配下のパス -> (status, content-type, body, cache-control)。"""
    dist = dist_dir()
    index = dist / "index.html"
    if not index.is_file():
        return 404, "text/plain; charset=utf-8", HINT.encode("utf-8"), "no-store"
    rel = unquote(path[len("/ui"):]).lstrip("/")
    if "\0" in rel:
        return 404, "text/plain; charset=utf-8", b"not found", "no-store"
    target = (dist / rel).resolve() if rel else index
    if not target.is_relative_to(dist.resolve()):  # ../ や絶対パスでの脱出
        return 404, "text/plain; charset=utf-8", b"not found", "no-store"
    if not target.is_file():
        if "." in target.name:  # 拡張子付き = アセット要求。SPA フォールバックしない
            return 404, "text/plain; charset=utf-8", b"not found", "no-store"
        target = index
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    cache = "public, max-age=31536000, immutable" if "assets" in target.relative_to(dist.resolve()).parts[:1] else "no-cache"
    return 200, ctype, target.read_bytes(), cache
