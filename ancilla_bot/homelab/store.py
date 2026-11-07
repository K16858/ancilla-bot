"""HomeLab の永続化（nodes 表）。DB は heartbeat と同じ ancilla.db を使う。"""

from __future__ import annotations

import hashlib
import hmac
import json
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

# 主体 × 情報源ごとの最新値だけ（履歴は持たない）。source: node | health
_SCHEMA_OBS = """
CREATE TABLE IF NOT EXISTS observations_latest (
    subject TEXT NOT NULL,
    source TEXT NOT NULL,
    value TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    PRIMARY KEY (subject, source)
)
"""

# 主体ごとの確定状態と確認待ち（events.py が使う）
_SCHEMA_STATUS = """
CREATE TABLE IF NOT EXISTS status_latest (
    subject TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    flags TEXT NOT NULL DEFAULT '[]',
    since TEXT NOT NULL,
    pending_state TEXT,
    pending_flags TEXT,
    pending_count INTEGER NOT NULL DEFAULT 0
)
"""

_SCHEMA_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    flags TEXT NOT NULL DEFAULT '[]',
    detected_at TEXT NOT NULL,
    evidence TEXT NOT NULL
)
"""

# Incident（incidents.py が使う）。event は link 表で結ぶ。role: own=自分の主体 / host=Host 優先で寄せた / impact=依存先優先で寄せた
_SCHEMA_INCIDENTS = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    detected_at TEXT NOT NULL,
    acknowledged_at TEXT,
    resolved_at TEXT,
    resolved_by TEXT,
    affected TEXT NOT NULL DEFAULT '[]',
    diagnosis TEXT,
    diagnosis_status TEXT NOT NULL DEFAULT 'none'
)
"""

_SCHEMA_INCIDENT_EVENTS = """
CREATE TABLE IF NOT EXISTS incident_events (
    incident_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'own',
    PRIMARY KEY (incident_id, event_id)
)
"""

# クライアント API（WebUI / Companion）用トークン。role: read | operate（operate は read を含む）
_SCHEMA_API_TOKENS = """
CREATE TABLE IF NOT EXISTS api_tokens (
    name TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
)
"""

API_ROLES = ("read", "operate")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    with closing(db._conn()) as c:
        c.row_factory = sqlite3.Row
        c.execute(_SCHEMA_NODES)
        c.execute(_SCHEMA_OBS)
        c.execute(_SCHEMA_STATUS)
        c.execute(_SCHEMA_EVENTS)
        c.execute(_SCHEMA_INCIDENTS)
        c.execute(_SCHEMA_INCIDENT_EVENTS)
        c.execute(_SCHEMA_API_TOKENS)
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


def put_observation(subject: str, source: str, value: dict, observed_at: str | None = None) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO observations_latest (subject, source, value, observed_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(subject, source) DO UPDATE SET value=excluded.value, observed_at=excluded.observed_at",
            (subject, source, json.dumps(value, ensure_ascii=False), observed_at or _now()),
        )


def get_observations() -> dict[tuple[str, str], tuple[dict, str]]:
    """(subject, source) -> (value, observed_at)"""
    with _conn() as c:
        return {
            (r["subject"], r["source"]): (json.loads(r["value"]), r["observed_at"])
            for r in c.execute("SELECT * FROM observations_latest")
        }


# ---- クライアント API トークン ----

def create_api_token(name: str, role: str) -> str:
    """トークンを発行する。同名は上書き（ローテーション）され、古いトークンは失効する。"""
    if role not in API_ROLES:
        raise ValueError(f"role は {' / '.join(API_ROLES)} のいずれか")
    token = secrets.token_urlsafe(32)
    with _conn() as c:
        c.execute(
            "INSERT INTO api_tokens (name, role, token_hash, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET role=excluded.role, token_hash=excluded.token_hash, "
            "created_at=excluded.created_at, revoked_at=NULL",
            (name, role, _hash(token), _now()),
        )
    return token


def revoke_api_token(name: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE api_tokens SET revoked_at=? WHERE name=? AND revoked_at IS NULL", (_now(), name)
        )
        return cur.rowcount > 0


def verify_api_token(token: str) -> str | None:
    """有効なトークンなら role、そうでなければ None（定数時間比較）。"""
    digest = _hash(token)
    found = None
    with _conn() as c:
        for r in c.execute("SELECT role, token_hash FROM api_tokens WHERE revoked_at IS NULL"):
            if hmac.compare_digest(r["token_hash"], digest):
                found = r["role"]
    return found


def list_api_tokens() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT name, role, created_at, revoked_at FROM api_tokens ORDER BY name")]
