"""SQLite persistence for requests, jobs, and FinOps."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from control_plane.config import db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_requests (
    id TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    consumer TEXT,
    consumer_class TEXT,
    mode TEXT,
    requested_model TEXT,
    served_model TEXT,
    swap INTEGER DEFAULT 0,
    queue_wait_ms INTEGER DEFAULT 0,
    infer_ms INTEGER DEFAULT 0,
    total_ms INTEGER DEFAULT 0,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    http_status INTEGER,
    ok INTEGER DEFAULT 0,
    error_class TEXT,
    trace_id TEXT,
    prompt_fingerprint TEXT,
    meta_json TEXT
);

CREATE TABLE IF NOT EXISTS llm_jobs (
    id TEXT PRIMARY KEY,
    created_ts REAL NOT NULL,
    completed_ts REAL,
    status TEXT NOT NULL,
    consumer TEXT,
    mode TEXT,
    model TEXT,
    webhook_url TEXT,
    webhook_secret TEXT,
    request_json TEXT,
    response_json TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS llm_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    ts REAL NOT NULL,
    verify_ok INTEGER,
    task_id TEXT,
    waste_tags TEXT,
    meta_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_requests_ts ON llm_requests(ts);
CREATE INDEX IF NOT EXISTS idx_llm_jobs_status ON llm_jobs(status);
"""

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
            yield conn
            conn.commit()
        finally:
            conn.close()


def insert_request(row: dict[str, Any]) -> str:
    rid = row.get("id") or str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO llm_requests (
                id, ts, consumer, consumer_class, mode, requested_model, served_model,
                swap, queue_wait_ms, infer_ms, total_ms, prompt_tokens, completion_tokens,
                http_status, ok, error_class, trace_id, prompt_fingerprint, meta_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                rid,
                row.get("ts", time.time()),
                row.get("consumer"),
                row.get("consumer_class"),
                row.get("mode"),
                row.get("requested_model"),
                row.get("served_model"),
                1 if row.get("swap") else 0,
                row.get("queue_wait_ms", 0),
                row.get("infer_ms", 0),
                row.get("total_ms", 0),
                row.get("prompt_tokens", 0),
                row.get("completion_tokens", 0),
                row.get("http_status"),
                1 if row.get("ok") else 0,
                row.get("error_class"),
                row.get("trace_id"),
                row.get("prompt_fingerprint"),
                json.dumps(row.get("meta") or {}),
            ),
        )
    return rid


def insert_job(job: dict[str, Any]) -> str:
    jid = job.get("id") or str(uuid.uuid4())
    with db() as conn:
        conn.execute(
            """
            INSERT INTO llm_jobs (
                id, created_ts, status, consumer, mode, model,
                webhook_url, webhook_secret, request_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                jid,
                job.get("created_ts", time.time()),
                job.get("status", "queued"),
                job.get("consumer"),
                job.get("mode"),
                job.get("model"),
                job.get("webhook_url"),
                job.get("webhook_secret"),
                json.dumps(job.get("request") or {}),
            ),
        )
    return jid


def update_job(jid: str, **fields: Any) -> None:
    sets: list[str] = []
    vals: list[Any] = []
    for k, v in fields.items():
        if k == "response":
            sets.append("response_json=?")
            vals.append(json.dumps(v))
        elif k == "request":
            sets.append("request_json=?")
            vals.append(json.dumps(v))
        else:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    vals.append(jid)
    with db() as conn:
        conn.execute(f"UPDATE llm_jobs SET {', '.join(sets)} WHERE id=?", vals)


def get_job(jid: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM llm_jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        return None
    return dict(row)


def list_requests(since_ts: float, limit: int = 100) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM llm_requests WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
            (since_ts, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def stats_since(since_ts: float) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS n,
                SUM(ok) AS ok_n,
                AVG(total_ms) AS avg_ms,
                SUM(prompt_tokens) AS tin,
                SUM(completion_tokens) AS tout,
                SUM(swap) AS swaps
            FROM llm_requests WHERE ts >= ?
            """,
            (since_ts,),
        ).fetchone()
        by_mode = conn.execute(
            """
            SELECT mode, COUNT(*) AS n, AVG(total_ms) AS avg_ms
            FROM llm_requests WHERE ts >= ? GROUP BY mode
            """,
            (since_ts,),
        ).fetchall()
    return {
        "requests": int(row["n"] or 0),
        "ok": int(row["ok_n"] or 0),
        "avg_total_ms": round(float(row["avg_ms"] or 0), 2),
        "prompt_tokens": int(row["tin"] or 0),
        "completion_tokens": int(row["tout"] or 0),
        "swaps": int(row["swaps"] or 0),
        "by_mode": {str(r["mode"]): {"n": r["n"], "avg_ms": r["avg_ms"]} for r in by_mode},
    }


def insert_feedback(payload: dict[str, Any]) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO llm_feedback (request_id, ts, verify_ok, task_id, waste_tags, meta_json)
            VALUES (?,?,?,?,?,?)
            """,
            (
                payload.get("request_id"),
                payload.get("ts", time.time()),
                1 if payload.get("verify_ok") else 0,
                payload.get("task_id"),
                json.dumps(payload.get("waste_tags") or []),
                json.dumps(payload.get("meta") or {}),
            ),
        )
