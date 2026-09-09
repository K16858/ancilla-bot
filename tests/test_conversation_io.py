from pathlib import Path

from ancilla_bot.memory.conversation_store import (
    append_overflow,
    load_active_history,
    load_overflow,
    save_active_history,
)


def test_save_and_load_active_history(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    save_active_history(
        [{"role": "user", "content": "hi", "ts": "2026-01-01 00:00"}]
    )
    assert load_active_history() == [
        {"role": "user", "content": "hi", "ts": "2026-01-01 00:00"}
    ]


def test_load_skips_broken_jsonl(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    (tmp_path / "active_history.jsonl").write_text(
        '{"role":"user","content":"ok"}\nnot-json\n',
        encoding="utf-8",
    )
    assert load_active_history() == [{"role": "user", "content": "ok"}]


def test_overflow_skips_system_events(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ANCILLA_CONVERSATION_DIR", str(tmp_path))
    append_overflow(
        [
            {"role": "user", "content": "[SYSTEM_EVENT idle]"},
            {"role": "assistant", "content": "pong"},
            {"role": "user", "content": "keep"},
        ]
    )
    overflow = load_overflow()
    assert [m["content"] for m in overflow] == ["keep"]
