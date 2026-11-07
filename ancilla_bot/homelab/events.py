"""状態変化の確認期間と Event 保存（LLM なし）。

報告間隔ごとに process() が全主体を判定し、確定状態（status_latest）と比べる。
新しい (state, flags) が 2 回連続で観測されたら確定し、Event を 1 件保存する（回復も同じ）。
初めて観測した主体は確定状態を記録するだけで Event は出さない（起動直後の Event 嵐を避ける）。

kind の決め方:
  Service: →unhealthy = service_down / →degraded = service_degraded / →healthy = recovered
  Host:    node_lost フラグが付いた = node_lost
           →degraded（フラグ無し）= disk_pressure（Node が fresh でないと degraded にならない）
           →unhealthy: Node が fresh なら disk_pressure、そうでなければ host_lost
           →unknown: healthy / degraded から来たときだけ host_lost（途絶したのに手掛かりが無い）。unhealthy から来たなら Event なし
           →healthy = recovered（unknown / degraded / unhealthy から）
  Service の →unknown は Event なし（確定状態だけ更新。unknown からの healthy も Event なし）。

PR 12 は subscribe(fn) で確定 Event を受け取る。fn(event: dict) は保存後に 1 件ずつ呼ばれる。
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from loguru import logger

from ancilla_bot.homelab import status as st
from ancilla_bot.homelab import store

CONFIRM_COUNT = 2

_subscribers: list[Callable[[dict], None]] = []
_started = time.monotonic()  # 起動直後は保存済みの観測が古く、Node 再接続前に host_lost が誤検知されるため猶予する
GRACE_INTERVALS = 3
GRACE_MIN_SEC = 90  # Node の再接続バックオフ上限(60s)より短くしない。ANCILLA_HOMELAB_INTERVAL を短くしても誤検知しない


def subscribe(fn: Callable[[dict], None]) -> None:
    _subscribers.append(fn)


def _kind(s: st.SubjectStatus, prev: str) -> str | None:
    if s.state == "healthy":
        return "recovered" if s.type == "host" or prev != "unknown" else None
    if s.type == "service":
        return {"unhealthy": "service_down", "degraded": "service_degraded"}.get(s.state)
    if "node_lost" in s.flags:
        return "node_lost"
    node_fresh = any(e["source"] == "node" and e["freshness"] == "fresh" for e in s.evidence)
    if s.state == "degraded" or (s.state == "unhealthy" and node_fresh):
        return "disk_pressure"
    if s.state == "unhealthy" or prev in ("healthy", "degraded"):  # unhealthy(途絶) / unknown
        return "host_lost"
    return None


def _save(s: st.SubjectStatus, prev: str, kind: str, now: str, c) -> dict:
    cur = c.execute(
        "INSERT INTO events (subject, kind, from_state, to_state, flags, detected_at, evidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (s.id, kind, prev, s.state, json.dumps(s.flags), now, json.dumps(s.evidence, ensure_ascii=False)),
    )
    return {"id": cur.lastrowid, "subject": s.id, "kind": kind, "from": prev, "to": s.state,
            "flags": list(s.flags), "detected_at": now, "evidence": s.evidence}


def update(statuses: dict[str, st.SubjectStatus], now: datetime | None = None) -> list[dict]:
    """判定結果を確定状態と比べ、確定した変化を Event として保存して返す（購読者も呼ぶ）。"""
    now_s = (now or datetime.now()).isoformat(timespec="seconds")
    out: list[dict] = []
    with store._conn() as c:
        rows = {r["subject"]: r for r in c.execute("SELECT * FROM status_latest")}
        for s in statuses.values():
            flags = json.dumps(sorted(s.flags))
            r = rows.get(s.id)
            if r is None:
                c.execute("INSERT INTO status_latest (subject, state, flags, since) VALUES (?, ?, ?, ?)",
                          (s.id, s.state, flags, now_s))
            elif (r["state"], r["flags"]) == (s.state, flags):
                if r["pending_count"]:
                    c.execute("UPDATE status_latest SET pending_state=NULL, pending_flags=NULL, "
                              "pending_count=0 WHERE subject=?", (s.id,))
            else:
                n = r["pending_count"] + 1 if (r["pending_state"], r["pending_flags"]) == (s.state, flags) else 1
                if n < CONFIRM_COUNT:
                    c.execute("UPDATE status_latest SET pending_state=?, pending_flags=?, pending_count=? "
                              "WHERE subject=?", (s.state, flags, n, s.id))
                else:
                    c.execute("UPDATE status_latest SET state=?, flags=?, since=?, pending_state=NULL, "
                              "pending_flags=NULL, pending_count=0 WHERE subject=?", (s.state, flags, now_s, s.id))
                    kind = _kind(s, r["state"])
                    if kind:
                        out.append(_save(s, r["state"], kind, now_s, c))
    out.sort(key=lambda e: e["kind"] not in ("host_lost", "node_lost"))  # Host 優先: 同じ回の通知は Host の Event から
    for e in out:  # 保存（commit）後に通知する
        for fn in _subscribers:
            try:
                fn(e)
            except Exception as ex:  # 購読者の失敗で他を止めない
                logger.warning("event subscriber failed: {}", ex)
    return out


def process(now: datetime | None = None, interval: float | None = None) -> list[dict]:
    kw = {} if interval is None else {"interval": interval}
    if time.monotonic() - _started < max(GRACE_MIN_SEC, GRACE_INTERVALS * (interval or st.REPORT_INTERVAL_SEC)):
        return []
    return update(st.evaluate_all(now, **kw), now)


# ---- ツール ----

def _since(v: str, now: datetime) -> str:
    m = re.fullmatch(r"(\d+)([mhd])", v)
    if m:
        unit = {"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return (now - timedelta(**{unit: int(m.group(1))})).isoformat(timespec="seconds")
    return datetime.fromisoformat(v).isoformat(timespec="seconds")


def _row(r) -> dict:
    return {"id": r["id"], "subject": r["subject"], "kind": r["kind"], "from": r["from_state"],
            "to": r["to_state"], "flags": json.loads(r["flags"]), "detected_at": r["detected_at"],
            "evidence": json.loads(r["evidence"])}


def last_event_id() -> int:
    with store._conn() as c:
        return c.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]


def events_after(after: int, limit: int = 200) -> list[dict]:
    """id が after より大きい Event を古い順に返す（SSE の追い付き用）。"""
    with store._conn() as c:
        return [_row(r) for r in c.execute("SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit))]


def homelab_get_events(subject: str = "", since: str = "", limit: Any = 50, **kwargs: Any) -> str:
    _ = kwargs
    sql, args = "SELECT * FROM events WHERE 1=1", []
    if str(subject or "").strip():
        sql += " AND subject=?"
        args.append(str(subject).strip())
    try:
        if str(since or "").strip():
            sql += " AND detected_at>=?"
            args.append(_since(str(since).strip(), datetime.now()))
        n = max(1, min(int(limit or 50), 500))
    except ValueError:
        return "Error: since は '24h' / '30m' / '7d' または ISO 時刻、limit は整数で指定してください"
    with store._conn() as c:
        rows = c.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, n)).fetchall()
    data = [_row(r) for r in rows]
    # evidence は外部由来のデータ。JSON のまま返し、指示としては扱わない
    return json.dumps(data, ensure_ascii=False, indent=2)
