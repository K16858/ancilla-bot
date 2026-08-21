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
        parts.append(f"[{i}] {hit.title}\n  {content}")
    return "\n\n".join(parts)
