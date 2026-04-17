"""SQLite job store for forge-fleet MVP."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            argv_json TEXT NOT NULL,
            session_id TEXT,
            meta_json TEXT,
            stdout TEXT,
            stderr TEXT,
            exit_code INTEGER,
            container_id TEXT,
            created REAL NOT NULL,
            updated REAL NOT NULL
        )
        """
    )
    _migrate_jobs_schema(conn)
    conn.commit()
    return conn


def _migrate_jobs_schema(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "running_started" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN running_started REAL")


def insert_job(conn: sqlite3.Connection, *, kind: str, argv: list[str], session_id: str, meta: dict[str, Any]) -> str:
    jid = uuid.uuid4().hex
    now = time.time()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (id, kind, status, argv_json, session_id, meta_json, stdout, stderr, exit_code, container_id, created, updated)
            VALUES (?, ?, 'queued', ?, ?, ?, '', '', NULL, NULL, ?, ?)
            """,
            (
                jid,
                kind,
                json.dumps(argv),
                session_id,
                json.dumps(meta),
                now,
                now,
            ),
        )
        conn.commit()
    return jid


def update_job(
    conn: sqlite3.Connection,
    jid: str,
    *,
    status: str | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    exit_code: int | None = None,
    container_id: str | None = None,
    running_started: float | None = None,
) -> None:
    now = time.time()
    fields: list[str] = ["updated = ?"]
    vals: list[Any] = [now]
    if status is not None:
        fields.append("status = ?")
        vals.append(status)
    if stdout is not None:
        fields.append("stdout = ?")
        vals.append(stdout[:1_000_000])
    if stderr is not None:
        fields.append("stderr = ?")
        vals.append(stderr[:256_000])
    if exit_code is not None:
        fields.append("exit_code = ?")
        vals.append(exit_code)
    if container_id is not None:
        fields.append("container_id = ?")
        vals.append(container_id)
    if running_started is not None:
        fields.append("running_started = ?")
        vals.append(running_started)
    vals.append(jid)
    with _lock:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()


def get_job(conn: sqlite3.Connection, jid: str) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,))
    row = cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["argv"] = json.loads(d.pop("argv_json") or "[]")
    d["meta"] = json.loads(d.pop("meta_json") or "{}")
    return d


def sum_accounted_core_seconds(conn: sqlite3.Connection) -> float:
    """Wall seconds jobs spent in ``running`` until a terminal status (1 logical core per job)."""
    cur = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE
                WHEN status IN ('completed', 'failed', 'cancelled')
                     AND running_started IS NOT NULL
                THEN MAX(0.0, updated - running_started)
                ELSE 0.0
            END
        ), 0.0) AS s
        FROM jobs
        """
    )
    row = cur.fetchone()
    if row is None:
        return 0.0
    return float(row["s"] or 0.0)


def count_jobs_by_status(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    return {str(r["status"]): int(r["n"]) for r in cur.fetchall()}


def list_jobs_summary(conn: sqlite3.Connection, *, limit: int = 150) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT id, kind, status, argv_json, session_id, exit_code, container_id, created, updated
        FROM jobs
        ORDER BY updated DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows: list[dict[str, Any]] = []
    for r in cur.fetchall():
        argv = json.loads(r["argv_json"] or "[]")
        preview = " ".join(str(x) for x in argv[:24])
        if len(preview) > 280:
            preview = preview[:280] + "…"
        rows.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "status": r["status"],
                "session_id": r["session_id"] or "",
                "argv_preview": preview,
                "exit_code": r["exit_code"],
                "container_id": r["container_id"],
                "created": r["created"],
                "updated": r["updated"],
            }
        )
    return rows
