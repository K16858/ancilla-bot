from pathlib import Path

from ancilla_bot.batch.summary_search import (
    append_summary_records,
    search_summaries_keyword,
)


def test_empty_query(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    assert search_summaries_keyword("") == []
    assert search_summaries_keyword("hello", n_results=0) == []


def test_score_and_rank(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    append_summary_records(
        [
            {"date": "2026-01-01", "summary": "alpha only", "start_index": 0},
            {"date": "2026-01-02", "summary": "alpha beta match", "start_index": 0},
            {"date": "2026-01-03", "summary": "alpha beta match", "start_index": 1},
        ]
    )
    hits = search_summaries_keyword("alpha beta", n_results=3)
    assert [h["document"] for h in hits] == ["alpha beta match", "alpha only"]
    assert hits[0]["metadata"]["score"] == 2
