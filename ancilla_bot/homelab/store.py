"""HomeLab の永続化（nodes 表）。DB は heartbeat と同じ ancilla.db を使う。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from typing import Iterator

from ancilla_bot.heartbeat import db

# last_seen がこの秒数以内なら「接続中」とみなす（接続中は channel が約 10 秒ごとに更新する）
CONNECTED_WITHIN_SEC = 30

_SCHEMA_NODES = """
CREATE TABLE IF NOT EXISTS nodes (
    host_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    revoked_at TEXT,
    last_seen TEXT,
    os TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    hostname TEXT NOT NULL DEFAULT ''
)
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with closing(db._conn()) as c:
        c.row_factory = sqlite3.Row
        c.execute(_SCHEMA_NODES)
        with c:
            yield c


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(host_id: str) -> str:
    """トークンを発行する。既存のトークンは上書きされ、失効する。"""
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute(
            "INSERT INTO nodes (host_id, token_hash, issued_at) VALUES (?, ?, ?) "
            "ON CONFLICT(host_id) DO UPDATE SET token_hash=excluded.token_hash, "
            "issued_at=excluded.issued_at, revoked_at=NULL",
            (host_id, _hash(token), _now()),
        )
    return token


def revoke(host_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE nodes SET revoked_at=? WHERE host_id=? AND revoked_at IS NULL",
            (_now(), host_id),
        )
        return cur.rowcount > 0


def verify_token(token: str) -> str | None:
    """有効なトークンなら紐付く Host ID、そうでなければ None（定数時間比較）。"""
    digest = _hash(token)
    found = None
    with _conn() as c:
        for r in c.execute("SELECT host_id, token_hash FROM nodes WHERE revoked_at IS NULL"):
            if hmac.compare_digest(r["token_hash"], digest):
                found = r["host_id"]
    return found


def is_active(host_id: str) -> bool:
    """失効・再発行されていないか（接続中の再確認用。トークン自体は接続時に検証済み）。"""
    with _conn() as c:
        r = c.execute("SELECT 1 FROM nodes WHERE host_id=? AND revoked_at IS NULL", (host_id,))
        return r.fetchone() is not None


def touch(host_id: str, *, os: str | None = None, version: str = "", hostname: str = "") -> None:
    """最終受信を更新する。os を渡したとき（hello）は報告内容も保存する。"""
    with _conn() as c:
        if os is None:
            c.execute("UPDATE nodes SET last_seen=? WHERE host_id=?", (_now(), host_id))
        else:
            c.execute(
                "UPDATE nodes SET last_seen=?, os=?, version=?, hostname=? WHERE host_id=?",
                (_now(), os, version, hostname, host_id),
            )


def list_nodes() -> list[dict]:
    with _conn() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM nodes ORDER BY host_id")]
    limit = datetime.now() - timedelta(seconds=CONNECTED_WITHIN_SEC)
    for r in rows:
        r["connected"] = (
            r["revoked_at"] is None
            and r["last_seen"] is not None
            and datetime.fromisoformat(r["last_seen"]) >= limit
        )
    return rows
