"""SQLite persistence for security events, blocks, and auth sessions."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


def ensure_security_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            source TEXT NOT NULL,
            route_class TEXT,
            path TEXT,
            method TEXT,
            verdict TEXT NOT NULL,
            rule TEXT,
            token_scope TEXT,
            session_id TEXT,
            request_id TEXT,
            severity TEXT NOT NULL DEFAULT 'low',
            detail_json TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_security_events_ts ON security_events (ts)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS security_blocks (
            source TEXT PRIMARY KEY,
            blocked_until REAL NOT NULL,
            rule TEXT NOT NULL,
            reason TEXT,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_auth_sessions (
            session_id TEXT PRIMARY KEY,
            secret_hash TEXT NOT NULL,
            session_secret TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            source TEXT NOT NULL,
            user_agent TEXT,
            minted_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            absolute_expires_at REAL NOT NULL,
            last_used_at REAL NOT NULL,
            token_id TEXT,
            revoked INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS peer_link_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            peer_id TEXT NOT NULL,
            ts REAL NOT NULL,
            ok INTEGER NOT NULL,
            rtt_ms REAL,
            throughput_mbps REAL,
            error TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_peer_link_samples_peer_ts ON peer_link_samples (peer_id, ts)"
    )


def insert_event(
    conn: sqlite3.Connection,
    *,
    source: str,
    verdict: str,
    severity: str = "low",
    route_class: str | None = None,
    path: str | None = None,
    method: str | None = None,
    rule: str | None = None,
    token_scope: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO security_events
            (ts, source, route_class, path, method, verdict, rule, token_scope, session_id, request_id, severity, detail_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            time.time(),
            source,
            route_class,
            path,
            method,
            verdict,
            rule,
            token_scope,
            session_id,
            request_id,
            severity,
            json.dumps(detail or {}),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def list_events(conn: sqlite3.Connection, since: float, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, ts, source, route_class, path, method, verdict, rule, token_scope, session_id, request_id, severity, detail_json
        FROM security_events WHERE ts >= ? ORDER BY ts DESC LIMIT ?
        """,
        (since, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        detail = {}
        try:
            detail = json.loads(str(row["detail_json"] or "{}"))
        except json.JSONDecodeError:
            detail = {}
        out.append(
            {
                "id": int(row["id"]),
                "ts": float(row["ts"]),
                "source": row["source"],
                "route_class": row["route_class"],
                "path": row["path"],
                "method": row["method"],
                "verdict": row["verdict"],
                "rule": row["rule"],
                "token_scope": row["token_scope"],
                "session_id": row["session_id"],
                "request_id": row["request_id"],
                "severity": row["severity"],
                "detail": detail,
            }
        )
    return out


def upsert_block(
    conn: sqlite3.Connection,
    source: str,
    blocked_until: float,
    rule: str,
    reason: str | None = None,
) -> None:
    now = time.time()
    conn.execute(
        """
        INSERT INTO security_blocks (source, blocked_until, rule, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            blocked_until=excluded.blocked_until,
            rule=excluded.rule,
            reason=excluded.reason,
            created_at=excluded.created_at
        """,
        (source, blocked_until, rule, reason, now),
    )
    conn.commit()


def remove_block(conn: sqlite3.Connection, source: str) -> bool:
    cur = conn.execute("DELETE FROM security_blocks WHERE source = ?", (source,))
    conn.commit()
    return int(cur.rowcount or 0) > 0


def is_blocked(conn: sqlite3.Connection, source: str, now: float | None = None) -> tuple[bool, str | None]:
    now = now if now is not None else time.time()
    row = conn.execute(
        "SELECT blocked_until, rule FROM security_blocks WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None:
        return False, None
    if float(row["blocked_until"]) <= now:
        conn.execute("DELETE FROM security_blocks WHERE source = ?", (source,))
        conn.commit()
        return False, None
    return True, str(row["rule"] or "")


def list_blocks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    now = time.time()
    rows = conn.execute(
        "SELECT source, blocked_until, rule, reason, created_at FROM security_blocks WHERE blocked_until > ?",
        (now,),
    ).fetchall()
    return [
        {
            "source": r["source"],
            "blocked_until": float(r["blocked_until"]),
            "rule": r["rule"],
            "reason": r["reason"],
            "created_at": float(r["created_at"]),
        }
        for r in rows
    ]
