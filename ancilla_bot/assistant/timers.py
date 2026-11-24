"""秒精度タイマーの永続化と CRUD。DB は heartbeat と同じ ancilla.db を使う。"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator

from loguru import logger

from ancilla_bot.heartbeat import db

MAX_DURATION_SEC = 86400 * 7
ACTIVE_STATUSES = ("running", "firing")
FINISHED_STATUSES = ("stopped", "cancelled")

_SCHEMA_TIMERS = """
CREATE TABLE IF NOT EXISTS timers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL DEFAULT '',
    duration_sec INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    fired_at TEXT,
    stopped_at TEXT,
    source TEXT NOT NULL DEFAULT 'user'
)
"""

_hooks_lock = threading.Lock()
_change_hooks: list[Callable[[str, dict[str, Any]], None]] = []


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_dt(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        return dt.astimezone()
    return dt


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with closing(db._conn()) as c:
        c.row_factory = sqlite3.Row
        c.execute(_SCHEMA_TIMERS)
        with c:
            yield c


def fmt_id(n: int) -> str:
    return f"TMR-{n:04d}"


def parse_id(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    s = str(raw or "").strip().upper()
    s = s[4:] if s.startswith("TMR-") else s
    if not s.isdigit():
        return None
    val = int(s)
    return val if val > 0 else None


def _validate_duration(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("duration_sec は整数で指定してください")
    try:
        sec = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration_sec は整数で指定してください") from exc
    if sec <= 0 or sec > MAX_DURATION_SEC:
        raise ValueError(f"duration_sec は 1〜{MAX_DURATION_SEC} 秒の範囲で指定してください")
    return sec


def _row_to_dict(row: sqlite3.Row, *, now: datetime | None = None) -> dict[str, Any]:
    ref = (now or _now()).replace(microsecond=0)
    status = str(row["status"])
    ends_at_str = str(row["ends_at"])
    remaining = 0
    if status == "running":
        remaining = max(0, int((_parse_dt(ends_at_str) - ref).total_seconds()))
    return {
        "id": fmt_id(int(row["id"])),
        "label": str(row["label"] or ""),
        "duration_sec": int(row["duration_sec"]),
        "status": status,
        "created_at": str(row["created_at"]),
        "ends_at": ends_at_str,
        "fired_at": row["fired_at"],
        "stopped_at": row["stopped_at"],
        "source": str(row["source"] or "user"),
        "remaining_sec": remaining,
    }


def subscribe_changes(cb: Callable[[str, dict[str, Any]], None]) -> None:
    with _hooks_lock:
        if cb not in _change_hooks:
            _change_hooks.append(cb)


def clear_hooks() -> None:
    with _hooks_lock:
        _change_hooks.clear()


def _emit(event: str, item: dict[str, Any]) -> None:
    with _hooks_lock:
        hooks = list(_change_hooks)
    for cb in hooks:
        try:
            cb(event, item)
        except Exception as exc:
            logger.warning("timer hook failed ({}): {}", event, exc)


def create_timer(duration_sec: int, *, label: str = "", source: str = "user") -> dict[str, Any]:
    sec = _validate_duration(duration_sec)
    clean_label = str(label or "").strip()
    clean_source = str(source or "user").strip() or "user"
    now = _now()
    base = now.replace(microsecond=0)
    created_at = _iso(base)
    ends_at = _iso(base + timedelta(seconds=sec))
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO timers (label, duration_sec, status, created_at, ends_at, source) "
            "VALUES (?, ?, 'running', ?, ?, ?)",
            (clean_label, sec, created_at, ends_at, clean_source),
        )
        row = c.execute("SELECT * FROM timers WHERE id=?", (cur.lastrowid,)).fetchone()
    item = _row_to_dict(row, now=now)
    _emit("changed", item)
    return item


def get_timer(timer_id: Any) -> dict[str, Any] | None:
    tid = parse_id(timer_id)
    if tid is None:
        return None
    now = _now()
    with _conn() as c:
        row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()
    return _row_to_dict(row, now=now) if row else None


def list_timers(*, include_finished: bool = False, _now_override: datetime | None = None) -> list[dict[str, Any]]:
    now = _now_override or _now()
    with _conn() as c:
        if include_finished:
            rows = c.execute(
                "SELECT * FROM timers "
                "ORDER BY CASE WHEN status IN ('running', 'firing') THEN 0 ELSE 1 END, "
                "ends_at ASC, id ASC"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM timers WHERE status IN ('running', 'firing') "
                "ORDER BY ends_at ASC, id ASC"
            ).fetchall()
    return [_row_to_dict(r, now=now) for r in rows]


def list_timers_payload(*, include_finished: bool = False) -> dict[str, Any]:
    now = _now()
    return {
        "server_now": _iso(now.replace(microsecond=0)),
        "timers": list_timers(include_finished=include_finished, _now_override=now),
    }


def update_timer(
    timer_id: Any,
    *,
    duration_sec: int | None = None,
    add_sec: int | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    if duration_sec is not None and add_sec is not None:
        raise ValueError("duration_sec と add_sec は同時に指定できません")
    tid = parse_id(timer_id)
    if tid is None:
        raise LookupError(f"未知のタイマー: {timer_id}")

    now = _now()
    now_sec = now.replace(microsecond=0)
    with _conn() as c:
        row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()
        if not row:
            raise LookupError(f"未知のタイマー: {timer_id}")

        status = str(row["status"])
        new_dur = int(row["duration_sec"])
        new_ends = str(row["ends_at"])
        new_label = str(row["label"] or "")

        if duration_sec is not None:
            if status != "running":
                raise ValueError(f"{fmt_id(tid)} は {status} のため時間を変更できません")
            new_dur = _validate_duration(duration_sec)
            new_ends = _iso(now_sec + timedelta(seconds=new_dur))
        elif add_sec is not None:
            if status != "running":
                raise ValueError(f"{fmt_id(tid)} は {status} のため時間を変更できません")
            if isinstance(add_sec, bool):
                raise ValueError("add_sec は整数で指定してください")
            try:
                delta = int(add_sec)
            except (TypeError, ValueError) as exc:
                raise ValueError("add_sec は整数で指定してください") from exc
            target_dt = _parse_dt(new_ends) + timedelta(seconds=delta)
            remaining = int((target_dt - now_sec).total_seconds())
            if remaining <= 0:
                raise ValueError("更新後の残り時間は 1 秒以上にしてください")
            created_dt = _parse_dt(str(row["created_at"]))
            span = int((target_dt - created_dt).total_seconds())
            if span <= 0 or span > MAX_DURATION_SEC:
                raise ValueError(f"タイマー合計時間は 1〜{MAX_DURATION_SEC} 秒の範囲で指定してください")
            new_dur = span
            new_ends = _iso(target_dt)

        if label is not None:
            new_label = str(label).strip()

        changed = (
            new_dur != int(row["duration_sec"])
            or new_ends != str(row["ends_at"])
            or new_label != str(row["label"] or "")
        )
        if changed:
            c.execute(
                "UPDATE timers SET label=?, duration_sec=?, ends_at=? WHERE id=?",
                (new_label, new_dur, new_ends, tid),
            )
            row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()

    item = _row_to_dict(row, now=now)
    if changed:
        _emit("changed", item)
    return item


def stop_timer(timer_id: Any = None) -> list[dict[str, Any]]:
    now = _now()
    now_iso = _iso(now.replace(microsecond=0))

    if timer_id is None or str(timer_id).strip() == "":
        with _conn() as c:
            rows = c.execute(
                "SELECT id FROM timers WHERE status='firing' ORDER BY id ASC"
            ).fetchall()
            if not rows:
                return []
            ids = [int(r["id"]) for r in rows]
            placeholders = ",".join("?" for _ in ids)
            c.execute(
                f"UPDATE timers SET status='stopped', stopped_at=? WHERE id IN ({placeholders})",
                [now_iso, *ids],
            )
            updated = c.execute(
                f"SELECT * FROM timers WHERE id IN ({placeholders}) ORDER BY id ASC",
                ids,
            ).fetchall()
        items = [_row_to_dict(r, now=now) for r in updated]
        for item in items:
            _emit("changed", item)
        return items

    tid = parse_id(timer_id)
    if tid is None:
        raise LookupError(f"未知のタイマー: {timer_id}")

    changed = False
    with _conn() as c:
        row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()
        if not row:
            raise LookupError(f"未知のタイマー: {timer_id}")
        status = str(row["status"])
        if status == "stopped":
            return [_row_to_dict(row, now=now)]
        if status != "firing":
            raise ValueError(f"{fmt_id(tid)} は {status} のため停止できません")
        c.execute(
            "UPDATE timers SET status='stopped', stopped_at=? WHERE id=?",
            (now_iso, tid),
        )
        row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()
        changed = True

    item = _row_to_dict(row, now=now)
    if changed:
        _emit("changed", item)
    return [item]


def cancel_timer(timer_id: Any) -> dict[str, Any]:
    tid = parse_id(timer_id)
    if tid is None:
        raise LookupError(f"未知のタイマー: {timer_id}")

    now = _now()
    now_iso = _iso(now.replace(microsecond=0))
    changed = False
    with _conn() as c:
        row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()
        if not row:
            raise LookupError(f"未知のタイマー: {timer_id}")
        status = str(row["status"])
        if status in FINISHED_STATUSES:
            return _row_to_dict(row, now=now)
        c.execute(
            "UPDATE timers SET status='cancelled', stopped_at=? WHERE id=?",
            (now_iso, tid),
        )
        row = c.execute("SELECT * FROM timers WHERE id=?", (tid,)).fetchone()
        changed = True

    item = _row_to_dict(row, now=now)
    if changed:
        _emit("changed", item)
    return item


def signature() -> tuple[tuple[Any, ...], ...]:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, status, ends_at, fired_at, stopped_at, label FROM timers ORDER BY id ASC"
        ).fetchall()
    return tuple((r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows)
