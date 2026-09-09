import json
from pathlib import Path

from ancilla_bot.notifications.store import append_notification, append_report


def test_append_notification_writes_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_NOTIFICATIONS_DIR", str(tmp_path))
    append_notification("hello", source="system", title="t", detail="d")
    line = (tmp_path / "pending.jsonl").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["message"] == "hello"
    assert rec["source"] == "system"
    assert rec["title"] == "t"
    assert rec["detail"] == "d"


def test_append_report_sets_source(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_NOTIFICATIONS_DIR", str(tmp_path))
    append_report("title", "body")
    rec = json.loads((tmp_path / "pending.jsonl").read_text(encoding="utf-8"))
    assert rec["source"] == "report"
    assert rec["title"] == "title"
    assert rec["message"] == "body"
    assert "detail" not in rec
