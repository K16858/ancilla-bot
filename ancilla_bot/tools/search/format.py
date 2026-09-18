"""検索結果の Observation 向け整形。"""

from ancilla_bot.tools.search.base import SearchHit


def format_hits(
    hits: list[SearchHit],
    *,
    content_max_chars: int | None = 300,
) -> str:
    if not hits:
        return "検索結果がありませんでした。"
    parts: list[str] = []
    for i, hit in enumerate(hits, 1):
        content = (hit.content or "").strip()
        if content_max_chars is not None and len(content) > content_max_chars:
            content = content[:content_max_chars] + "..."
        url = (hit.url or "").strip()
        line = f"[{i}] {hit.title}"
        if url:
            line += f"\n  {url}"
        if content:
            line += f"\n  {content}"
        parts.append(line)
    return "\n\n".join(parts)
