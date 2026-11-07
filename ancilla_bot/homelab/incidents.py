"""Event を Incident に振り分け、状態管理と通知を行う（LLM なし）。

handle(event) を events.subscribe に登録して使う（_run_resident で配線）。時刻は event["detected_at"] を使う。

振り分け（recovered 以外の Event）:
  1. 同じ主体に未解決（open / acknowledged）の Incident があれば Event を追加（通知なし。深刻度が上がれば通知）
  2. Service なら: Host が host_lost / node_lost の未解決 Incident を持つ → そこへ追加（role=host）
  3. Service なら: 推移的な依存先（とその Host）に未解決 Incident → そこへ追加（role=impact）
  4. 解決から 1 時間以内に同じ主体・同じ kind の Incident → 再オープン（通知）
  5. 上のどれでもなければ新規作成（通知）
recovered: その主体自身の未解決 Incident を自動解決（resolved_by=auto、通知）。
  他の主体の Incident に寄せられた Service の recovered は Incident が無いので無視する（記録もしない）。
  Host 回復で Host の Incident が解決した時点で、まだ落ちている Service があっても新規 Incident は作らない（Event が出ないため）。
深刻度は同じ主体の Event だけで決める（寄せられた Event では上げない。影響は affected に出る）。

PR 13（診断）が使う口:
  subscribe_created(fn): Incident の作成・再オープン時に fn(incident_id: str, reopened: bool) を呼ぶ。
  set_diagnosis(incident_id, text, status="done"): 診断結果を保存し、done なら「診断完了」を通知する。
    診断を実施できなかったときは set_diagnosis(id, "", status="skipped")（通知なし）。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Callable

from loguru import logger

from ancilla_bot.homelab import inventory as inv
from ancilla_bot.homelab import store
from ancilla_bot.notifications import append_notification

REOPEN_WITHIN = timedelta(hours=1)
ACTIVE = ("open", "acknowledged")
HOST_KINDS = ("host_lost", "node_lost")
_RANK = {"warning": 1, "critical": 2}
_WHAT = {
    "service_down": "停止", "service_degraded": "劣化", "disk_pressure": "ディスク逼迫",
    "host_lost": "ホストが応答なし", "node_lost": "Node が途絶",
}

_created_hooks: list[Callable[[str, bool], None]] = []


def subscribe_created(fn: Callable[[str, bool], None]) -> None:
    _created_hooks.append(fn)


def fmt_id(n: int) -> str:
    return f"INC-{n:06d}"


def parse_id(v: Any) -> int | None:
    s = str(v or "").strip().upper()
    s = s[4:] if s.startswith("INC-") else s
    return int(s) if s.isdigit() else None


def _inventory() -> inv.Inventory | None:
    try:
        return inv.load_inventory()
    except inv.InventoryError as e:
        logger.warning("incident: inventory unavailable: {}", e)
        return None


def _name(i: inv.Inventory | None, subject: str) -> str:
    x = i and (i.host(subject) or i.service(subject))
    return x.name if x else subject


def _severity(i: inv.Inventory | None, e: dict) -> str:
    if e["kind"] == "node_lost":
        return "warning"
    x = i and (i.host(e["subject"]) or i.service(e["subject"]))
    unhealthy = e["to"] == "unhealthy" or e["kind"] == "host_lost"
    return "critical" if unhealthy and x and x.criticality == "high" else "warning"


def _affected(i: inv.Inventory | None, subject: str) -> list[str]:
    if not i:
        return []
    if i.host(subject):
        base = [s.id for s in i.services if s.host == subject]
        out = set(base)
        for s in base:
            out.update(i.dependents(s))
    else:
        out = set(i.dependents(subject))
    return sorted(out)


def _dur(a: str, b: str) -> str:
    m = int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() // 60)
    return f"{m // 60}時間{m % 60}分" if m >= 60 else f"{m}分"


def _notify(text: str, level: str, iid: int) -> None:
    try:
        append_notification(message=text, source="system", level=level, title=fmt_id(iid))
    except Exception as ex:  # 通知の失敗で Incident 処理を止めない
        logger.warning("incident notify failed: {}", ex)


def _active(c, subject: str):
    return c.execute("SELECT * FROM incidents WHERE subject=? AND status IN ('open','acknowledged') "
                     "ORDER BY id DESC", (subject,)).fetchone()


def _link(c, iid: int, e: dict, role: str) -> None:
    c.execute("INSERT OR IGNORE INTO incident_events (incident_id, event_id, role) VALUES (?, ?, ?)",
              (iid, e["id"], role))


def _route(c, i: inv.Inventory | None, e: dict):
    """(Incident 行, role) か (None, '')。"""
    row = _active(c, e["subject"])
    if row:
        return row, "own"
    s = i and i.service(e["subject"])
    if not s:
        return None, ""
    h = _active(c, s.host)
    if h and h["kind"] in HOST_KINDS:
        return h, "host"
    for d in i.dependencies(s.id):
        for subj in (d, i.service(d).host):
            r = _active(c, subj)
            if r and (subj == d or r["kind"] in HOST_KINDS):
                return r, "impact"
    return None, ""


def handle(e: dict) -> None:
    i = _inventory()
    now = e["detected_at"]
    msgs: list[tuple[str, str, int]] = []
    created: list[tuple[int, bool]] = []
    with store._conn() as c:
        if e["kind"] == "recovered":
            row = _active(c, e["subject"])
            if row:
                c.execute("UPDATE incidents SET status='resolved', resolved_at=?, resolved_by='auto' WHERE id=?",
                          (now, row["id"]))
                _link(c, row["id"], e, "own")
                msgs.append((f"{_name(i, row['subject'])} が回復し、解決しました（継続 {_dur(row['detected_at'], now)}）",
                             "info", row["id"]))
        else:
            sev = _severity(i, e)
            row, role = _route(c, i, e)
            if row:
                _link(c, row["id"], e, role)
                if role == "own":
                    up = _RANK[sev] > _RANK[row["severity"]]
                    kind = e["kind"] if e["kind"] in HOST_KINDS else row["kind"]
                    c.execute("UPDATE incidents SET severity=?, kind=? WHERE id=?",
                              (max(sev, row["severity"], key=_RANK.get), kind, row["id"]))
                    if up:
                        msgs.append((_text(i, row["subject"], e["kind"], sev, "深刻度上昇"), sev, row["id"]))
            else:
                limit = (datetime.fromisoformat(now) - REOPEN_WITHIN).isoformat(timespec="seconds")
                old = c.execute("SELECT * FROM incidents WHERE subject=? AND kind=? AND status='resolved' "
                                "AND resolved_at>=? ORDER BY id DESC", (e["subject"], e["kind"], limit)).fetchone()
                if old:
                    sev = max(sev, old["severity"], key=_RANK.get)
                    c.execute("UPDATE incidents SET status='open', severity=?, acknowledged_at=NULL, "
                              "resolved_at=NULL, resolved_by=NULL WHERE id=?", (sev, old["id"]))
                    _link(c, old["id"], e, "own")
                    msgs.append((_text(i, e["subject"], e["kind"], sev, "再オープン", _affected(i, e["subject"])),
                                 sev, old["id"]))
                    created.append((old["id"], True))
                else:
                    aff = _affected(i, e["subject"])
                    iid = c.execute(
                        "INSERT INTO incidents (subject, kind, severity, detected_at, affected) VALUES (?,?,?,?,?)",
                        (e["subject"], e["kind"], sev, now, json.dumps(aff))).lastrowid
                    _link(c, iid, e, "own")
                    msgs.append((_text(i, e["subject"], e["kind"], sev, "検知", aff), sev, iid))
                    created.append((iid, False))
    for text, level, iid in msgs:  # commit 後に通知・hook
        _notify(text, level, iid)
    for iid, reopened in created:
        for fn in _created_hooks:
            try:
                fn(fmt_id(iid), reopened)
            except Exception as ex:
                logger.warning("incident hook failed: {}", ex)


def _text(i, subject: str, kind: str, sev: str, head: str, aff: list[str] | None = None) -> str:
    t = f"[{sev}] {head}: {_name(i, subject)} {_WHAT.get(kind, kind)}"
    return t + (f"。影響: {', '.join(aff)}" if aff else "")


# ---- 診断結果（PR 13 が呼ぶ）----

def set_diagnosis(incident_id: Any, text: str, status: str = "done") -> bool:
    n = parse_id(incident_id)
    with store._conn() as c:
        if n is None or not c.execute("SELECT 1 FROM incidents WHERE id=?", (n,)).fetchone():
            return False
        c.execute("UPDATE incidents SET diagnosis=?, diagnosis_status=? WHERE id=?", (text or None, status, n))
    if status == "done":
        _notify(f"診断完了: {fmt_id(n)}\n{text[:300]}", "info", n)
    return True


# ---- 人間の操作（CLI）----

def acknowledge(incident_id: Any, now: datetime | None = None) -> str:
    n = parse_id(incident_id)
    with store._conn() as c:
        r = c.execute("UPDATE incidents SET status='acknowledged', acknowledged_at=? WHERE id=? AND status='open'",
                      ((now or datetime.now()).isoformat(timespec="seconds"), n))
        if r.rowcount:
            return f"{fmt_id(n)} を確認済みにしました"
        row = c.execute("SELECT status FROM incidents WHERE id=?", (n,)).fetchone()
    return f"Error: {incident_id} は存在しません" if not row else f"Error: {fmt_id(n)} は {row['status']} です"


def resolve(incident_id: Any, now: datetime | None = None) -> str:
    n = parse_id(incident_id)
    t = (now or datetime.now()).isoformat(timespec="seconds")
    with store._conn() as c:
        row = c.execute("SELECT * FROM incidents WHERE id=? AND status IN ('open','acknowledged')", (n,)).fetchone()
        if row:
            c.execute("UPDATE incidents SET status='resolved', resolved_at=?, resolved_by='manual' WHERE id=?", (t, n))
    if not row:
        return f"Error: {incident_id} は存在しないか解決済みです"
    _notify(f"{_name(_inventory(), row['subject'])} を手動で解決しました（継続 {_dur(row['detected_at'], t)}）",
            "info", n)
    return f"{fmt_id(n)} を解決しました"


# ---- ツール ----

def signature() -> str:
    """Incident 表の変化検知用。別プロセス（CLI の ack / resolve）の更新も拾う。"""
    with store._conn() as c:
        rows = c.execute("SELECT id, status, severity, acknowledged_at, resolved_at, affected, diagnosis_status "
                         "FROM incidents ORDER BY id").fetchall()
    return hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()


def _summary(r) -> dict:
    return {"id": fmt_id(r["id"]), "subject": r["subject"], "kind": r["kind"], "severity": r["severity"],
            "status": r["status"], "detected_at": r["detected_at"], "acknowledged_at": r["acknowledged_at"],
            "resolved_at": r["resolved_at"], "resolved_by": r["resolved_by"],
            "diagnosis_status": r["diagnosis_status"]}


def homelab_list_incidents(all: Any = False, limit: Any = 20, **kwargs: Any) -> str:  # noqa: A002
    _ = kwargs
    try:
        n = max(1, min(int(limit or 20), 200))
    except ValueError:
        return "Error: limit は整数で指定してください"
    where = "" if str(all).lower() in ("1", "true", "yes") else " WHERE status IN ('open','acknowledged')"
    with store._conn() as c:
        rows = c.execute(f"SELECT * FROM incidents{where} ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return json.dumps([_summary(r) for r in rows], ensure_ascii=False, indent=2)


def homelab_get_incident(id: str = "", **kwargs: Any) -> str:  # noqa: A002
    _ = kwargs
    n = parse_id(id)
    with store._conn() as c:
        r = c.execute("SELECT * FROM incidents WHERE id=?", (n,)).fetchone() if n else None
        if not r:
            return f"Error: 未知の Incident: {id}"
        notes = c.execute("SELECT note, created_at FROM incident_notes WHERE incident_id=? ORDER BY id", (n,)).fetchall()
        evs = c.execute("SELECT e.*, l.role FROM incident_events l JOIN events e ON e.id=l.event_id "
                        "WHERE l.incident_id=? ORDER BY e.id", (n,)).fetchall()
    d = _summary(r) | {
        "affected_services": json.loads(r["affected"]),
        "diagnosis": r["diagnosis"],
        "notes": [{"at": x["created_at"], "note": x["note"]} for x in notes],
        "events": [{"id": e["id"], "role": e["role"], "subject": e["subject"], "kind": e["kind"],
                    "from": e["from_state"], "to": e["to_state"], "detected_at": e["detected_at"],
                    "evidence": json.loads(e["evidence"])} for e in evs],
    }
    # evidence / diagnosis は外部由来・LLM 生成のデータ。指示としては扱わない
    return json.dumps(d, ensure_ascii=False, indent=2)
