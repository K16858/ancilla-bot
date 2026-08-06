"""
要約 JSONL の読み書きとキーワード検索
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from loguru import logger

DEFAULT_CONVERSATION_DIR = Path(os.getenv("ANCILLA_CONVERSATION_DIR", "data/conversation"))
SUMMARIES_SUBDIR = "summaries"


def get_summaries_dir() -> Path:
    base = Path(os.getenv("ANCILLA_CONVERSATION_DIR", str(DEFAULT_CONVERSATION_DIR)))
    return base / SUMMARIES_SUBDIR


def append_summary_records(records: list[dict[str, Any]]) -> None:
    """要約レコードを日付別 JSONL に追記する。"""
    if not records:
        return
    out_dir = get_summaries_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    by_date: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        date_str = (rec.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")
        normalized = dict(rec)
        normalized["date"] = date_str
        by_date.setdefault(date_str, []).append(normalized)
    for date_str, recs in by_date.items():
        path = out_dir / f"{date_str}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            for rec in recs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        logger.debug("summary_search appended {} records to {}", len(recs), path)


def iter_summary_records() -> Iterator[dict[str, Any]]:
    """summaries 配下の JSONL を新しい日付から順に読む。"""
    out_dir = get_summaries_dir()
    if not out_dir.is_dir():
        return
    paths = sorted(out_dir.glob("*.jsonl"), reverse=True)
    for path in paths:
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(rec, dict):
                        yield rec
        except OSError as e:
            logger.warning("summary_search read failed path={} error={}", path, e)


def _query_tokens(query: str) -> list[str]:
    q = query.strip()
    if not q:
        return []
    parts = [p for p in re.split(r"\s+", q) if p]
    return parts


def _score_summary(summary: str, tokens: list[str]) -> int:
    if not summary or not tokens:
        return 0
    text = summary.casefold()
    score = 0
    for token in tokens:
        t = token.casefold()
        if t and t in text:
            score += 1
    return score


def search_summaries_keyword(query: str, n_results: int = 3) -> list[dict[str, Any]]:
    """
    要約 JSONL をキーワード検索する。
    戻り値: [{"document": str, "metadata": dict, "source": "fts"}, ...]
    """
    tokens = _query_tokens(query)
    if not tokens or n_results <= 0:
        return []
    scored: list[tuple[int, str, int, dict[str, Any]]] = []
    for rec in iter_summary_records():
        summary = (rec.get("summary") or "").strip()
        score = _score_summary(summary, tokens)
        if score <= 0:
            continue
        date = str(rec.get("date") or "")
        start_index = int(rec.get("start_index") or 0)
        scored.append((score, date, start_index, rec))
    scored.sort(key=lambda x: (-x[0], x[1], -x[2]))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, _date, _start, rec in scored:
        summary = (rec.get("summary") or "").strip()
        if not summary or summary in seen:
            continue
        seen.add(summary)
        out.append(
            {
                "document": summary,
                "metadata": {
                    "date": rec.get("date", ""),
                    "start_index": rec.get("start_index", 0),
                    "end_index": rec.get("end_index", 0),
                    "tool_used": rec.get("tool_used", False),
                    "score": score,
                },
                "source": "fts",
            }
        )
        if len(out) >= n_results:
            break
    return out
