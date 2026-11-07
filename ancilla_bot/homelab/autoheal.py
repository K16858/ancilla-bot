"""Self-Healing（Phase 6）: homelab.yaml で restart: auto / auto_dry_run と宣言したサービスだけ、承認なしで再起動する。

判断は通常のコード（LLM の診断は並行して走るが、可否は決めない）。Incident の作成・再オープンで enqueue され、
単一の worker スレッドが 1 件ずつ処理する（Node への命令は最大 60 秒かかるため）。
条件は実行の直前にその都度評価し、満たさなければ理由を記録して何もしない。
  1. Incident が service_down で、Incident の主体がそのサービス自身
  2. restart が auto / auto_dry_run と宣言されている（未宣言は無言）
  3. 停止スイッチ（ancilla homelab autoheal on|off|status。既定 on）
  4. Host が生きていて、Node が接続中かつ fresh（node_lost でない）
  5. 依存先（推移的）とその Host に未解決 Incident がない
  6. 回数制限: Incident ごとに自動再起動 1 回、サービスごとに 24 時間で 3 回（dry-run は数えない）
人に知らせるべき理由（3〜6）で見送ったときは、Incident ごとに 1 回だけ通知する。
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime, timedelta

from loguru import logger

from ancilla_bot.homelab import channel, incidents, operations, status, store
from ancilla_bot.homelab import inventory as inv
from ancilla_bot.notifications import append_notification

MAX_PER_INCIDENT = 1
MAX_PER_SERVICE_24H = 3
SWITCH_KEY = "autoheal"
SKIP_MARK = "[autoheal:skip]"

_q: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None


# ---- 停止スイッチ ----

def is_enabled() -> bool:
    return store.get_setting(SWITCH_KEY, "on") != "off"


def set_enabled(on: bool) -> None:
    store.set_setting(SWITCH_KEY, "on" if on else "off")


# ---- 判定 ----

def _count(c, target: str, since: str | None = None, incident: int | None = None, decision: str = "auto") -> int:
    sql = "SELECT COUNT(*) FROM action_log WHERE requested_by='autoheal' AND action='restart' AND decision=? AND target=?"
    args: list = [decision, target]
    if since:
        sql += " AND started_at>=?"
        args.append(since)
    if incident is not None:
        sql += " AND incident_id=?"
        args.append(incident)
    return c.execute(sql, args).fetchone()[0]


def _note(n: int, text: str) -> None:
    operations._note(n, f"[autoheal] {text}")


def _notify(n: int, text: str, level: str = "warning") -> None:
    try:
        append_notification(message=text, source="system", level=level, title=incidents.fmt_id(n))
    except Exception as e:
        logger.warning("autoheal notify failed: {}", e)


def _skip(n: int, why: str, service: str) -> str:
    """人に知らせる見送り。Incident ごとに 1 回だけ通知する。"""
    with store._conn() as c:
        seen = c.execute("SELECT 1 FROM incident_notes WHERE incident_id=? AND note LIKE ?",
                         (n, SKIP_MARK + "%")).fetchone()
        if not seen:
            c.execute("INSERT INTO incident_notes (incident_id, note, created_at) VALUES (?,?,?)",
                      (n, f"{SKIP_MARK} {why}", datetime.now().isoformat(timespec="seconds")))
    if not seen:
        _notify(n, f"{service} は自動再起動しませんでした: {why}（{incidents.fmt_id(n)}）。必要なら承認付きで再起動してください")
    logger.info("autoheal skip {} {}: {}", incidents.fmt_id(n), service, why)
    return "skipped: " + why


def _blocker(i: inv.Inventory, s: inv.Service, n: int) -> str | None:
    """見送る理由（無ければ None）。Host / Node / 依存先 / 回数制限の順。"""
    try:
        st = status.evaluate_all(i=i)
    except Exception as e:
        return f"状態を判定できません（{e}）"
    h = st.get(s.host)
    node_fresh = h and any(e["source"] == "node" and e["freshness"] == "fresh" for e in h.evidence)
    if not h or h.state in ("unhealthy", "unknown"):
        return f"Host {s.host} が応答していません"
    if "node_lost" in h.flags or not node_fresh or not channel.is_connected(s.host):
        return f"Host {s.host} の Node が接続・報告していません"
    with store._conn() as c:
        for d in i.dependencies(s.id):
            for subj in (d, i.service(d).host):
                r = c.execute("SELECT id FROM incidents WHERE subject=? AND status IN ('open','acknowledged')",
                              (subj,)).fetchone()
                if r:
                    return f"依存先 {subj} に未解決の Incident があります（{incidents.fmt_id(r['id'])}）"
        since = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        if _count(c, s.id, since=since) >= MAX_PER_SERVICE_24H:
            return f"24 時間の自動再起動回数の上限（{MAX_PER_SERVICE_24H} 回）に達しています"
    return None


def process(incident_id: str) -> str:
    """1 件処理して結果の説明を返す（テスト用）。"""
    n = incidents.parse_id(incident_id)
    with store._conn() as c:
        row = c.execute("SELECT * FROM incidents WHERE id=?", (n,)).fetchone() if n else None
    if not row or row["kind"] != "service_down" or row["status"] not in incidents.ACTIVE:
        return "ignored: service_down の未解決 Incident ではありません"
    try:
        i = inv.load_inventory()
    except inv.InventoryError as e:
        return f"ignored: {e}"
    s = i.service(row["subject"])  # Incident の主体が Host なら None（Host 配下に寄せられた Incident は対象外）
    mode = s and s.actions.get("restart")
    if mode not in ("auto", "auto_dry_run"):
        return "ignored: restart が auto 宣言されていません"
    if not is_enabled():
        return _skip(n, "自動再起動の停止スイッチが off です", s.id)
    with store._conn() as c:
        if _count(c, s.id, incident=n, decision="dry_run") >= 1 or _count(c, s.id, incident=n) >= MAX_PER_INCIDENT:
            return "ignored: この Incident では実施済みです"
    why = _blocker(i, s, n)
    if why:
        return _skip(n, why, s.id)
    if not is_enabled():  # 実行の直前にもう一度。off は待機中の分にも即座に効く
        return _skip(n, "自動再起動の停止スイッチが off です", s.id)

    iid = incidents.fmt_id(n)
    if mode == "auto_dry_run":
        operations.run_action("restart", s.id, requested_by="autoheal", dry_run=True)
        _notify(n, f"自動再起動するはずだった: {s.id}（{iid}）", "info")
        _note(n, "auto_dry_run: 再起動するはずでしたが送信していません")
        return "dry_run"

    _notify(n, f"自動再起動します: {s.id}（{iid}）", "info")

    def done(ok: bool, result: str) -> None:
        if ok:
            _note(n, f"自動再起動が成功しました。{result}")
        else:
            _note(n, f"自動再起動後も回復しませんでした。自動処理を止めました。{result}")
            _notify(n, f"自動再起動で {s.id} は回復しませんでした（{iid}）。自動処理は止め、承認待ちに戻します。"
                       "Ancilla に再起動を依頼すると、通常の承認を経て実行できます")

    res = operations.run_action("restart", s.id, requested_by="autoheal", on_done=done)
    if not res["ok"]:
        _note(n, f"自動再起動を実行できませんでした: {res['error']}")
        _notify(n, f"自動再起動に失敗しました: {s.id}（{iid}）: {res['error']}。承認待ちに戻します")
        return "failed: " + res["error"]
    return "restarted"


# ---- worker ----

def enqueue(incident_id: str, reopened: bool = False) -> None:
    _ = reopened
    _q.put(incident_id)


def _loop() -> None:
    while True:
        iid = _q.get()
        try:
            process(iid)
        except Exception as e:
            logger.warning("autoheal worker: {}", e)
        finally:
            _q.task_done()


def start_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_loop, daemon=True, name="homelab-autoheal")
        _worker.start()
