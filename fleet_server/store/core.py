"""SQLite job store for forge-fleet MVP."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fleet_server import telemetry_periods, versioning

_lock = threading.Lock()


def _ensure_telemetry_table(conn: sqlite3.Connection) -> None:
    """Idempotent: ``telemetry_samples`` + index (also created by schema v3 migration)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_samples_ts ON telemetry_samples (ts)")


def _ensure_energy_ledger(conn: sqlite3.Connection) -> None:
    """Single-row cumulative energy (Wh) from RAPL counters + NVIDIA power × time."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_energy_ledger (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cumulative_wh_rapl REAL NOT NULL DEFAULT 0,
            cumulative_wh_gpu REAL NOT NULL DEFAULT 0,
            updated REAL NOT NULL DEFAULT 0,
            last_ts REAL,
            last_rapl_uj REAL,
            last_gpu_power_w REAL
        )
        """
    )
    row = conn.execute("SELECT id FROM fleet_energy_ledger WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO fleet_energy_ledger
                (id, cumulative_wh_rapl, cumulative_wh_gpu, updated, last_ts, last_rapl_uj, last_gpu_power_w)
            VALUES (1, 0, 0, 0, NULL, NULL, NULL)
            """
        )


def _ensure_cooldown_table(conn: sqlite3.Connection) -> None:
    """LLM thermal guard (and similar) report wall-clock delay intervals here."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_cooldown_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            duration_s REAL NOT NULL,
            kind TEXT,
            meta_json TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fleet_cooldown_ts ON fleet_cooldown_events (ts)")


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
    _migrate_fleet_schema_table(conn)
    _sync_fleet_version_row(conn)
    _ensure_telemetry_table(conn)
    _ensure_energy_ledger(conn)
    _ensure_cooldown_table(conn)
    conn.commit()
    return conn


def _migrate_jobs_schema(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "running_started" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN running_started REAL")


def _migrate_fleet_schema_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_schema (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            package_semver TEXT NOT NULL,
            db_schema_version INTEGER NOT NULL,
            updated REAL NOT NULL
        )
        """
    )


def _sync_fleet_version_row(conn: sqlite3.Connection) -> None:
    """Persist package semver + DB schema revision (schema bumps with migrations in this module)."""
    now = time.time()
    sem = versioning.package_semver()
    code_schema = int(versioning.FLEET_DB_SCHEMA_VERSION)
    row = conn.execute("SELECT package_semver, db_schema_version FROM fleet_schema WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO fleet_schema (id, package_semver, db_schema_version, updated) VALUES (1, ?, ?, ?)",
            (sem, 1, now),
        )
        stored_schema = 1
    else:
        stored_schema = int(row["db_schema_version"] or 1)
    new_schema = stored_schema
    if code_schema > stored_schema:
        _run_fleet_schema_migrations(conn, stored_schema, code_schema)
        new_schema = code_schema
    elif code_schema < stored_schema:
        # Database was upgraded by a newer Fleet binary — do not downgrade schema from older code.
        new_schema = stored_schema
    conn.execute(
        "UPDATE fleet_schema SET package_semver = ?, db_schema_version = ?, updated = ? WHERE id = 1",
        (sem, new_schema, now),
    )


def _run_fleet_schema_migrations(conn: sqlite3.Connection, from_v: int, to_v: int) -> None:
    """Apply incremental SQLite migrations when ``versioning.FLEET_DB_SCHEMA_VERSION`` increases."""
    v = int(from_v)
    target = int(to_v)
    while v < target:
        next_v = v + 1
        if next_v == 2:
            # v2 introduces ``fleet_schema`` itself — nothing to ALTER on jobs; table already created.
            pass
        # elif next_v == 3: ...
        elif next_v == 3:
            _ensure_telemetry_table(conn)
        elif next_v == 4:
            _ensure_energy_ledger(conn)
        elif next_v == 5:
            _ensure_cooldown_table(conn)
        elif next_v == 6:
            _ensure_job_worker_bridge_columns(conn)
        else:
            raise RuntimeError(f"fleet_schema migration missing for {v} -> {next_v}")
        v = next_v


def get_fleet_version_row(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT package_semver, db_schema_version, updated FROM fleet_schema WHERE id = 1"
    ).fetchone()
    if row is None:
        return {
            "package_semver": versioning.package_semver(),
            "db_schema_version": int(versioning.FLEET_DB_SCHEMA_VERSION),
            "updated": None,
        }
    return {
        "package_semver": str(row["package_semver"] or ""),
        "db_schema_version": int(row["db_schema_version"] or 1),
        "updated": float(row["updated"]) if row["updated"] is not None else None,
    }


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


def _safe_json_dict(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    try:
        o = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return None
    return o if isinstance(o, dict) else None


def _ensure_job_worker_bridge_columns(conn: sqlite3.Connection) -> None:
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "worker_progress_json" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN worker_progress_json TEXT")
    if "worker_result_json" not in cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN worker_result_json TEXT")


def get_job(conn: sqlite3.Connection, jid: str) -> dict[str, Any] | None:
    cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (jid,))
    row = cur.fetchone()
    if row is None:
        return None
    d = dict(row)
    d["argv"] = json.loads(d.pop("argv_json") or "[]")
    d["meta"] = json.loads(d.pop("meta_json") or "{}")
    wp_raw = d.pop("worker_progress_json", None)
    wr_raw = d.pop("worker_result_json", None)
    d["worker_progress"] = _safe_json_dict(wp_raw)
    d["worker_result"] = _safe_json_dict(wr_raw)
    return d


def authenticate_workspace_worker_bridge(
    conn: sqlite3.Connection, jid: str, token: str
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Validate ``X-Workspace-Worker-Token`` against ``meta.workspace_worker_token``.
    Returns ``(job_row, None)`` or ``(None, error_tag)``.
    """
    row = get_job(conn, jid)
    if row is None:
        return None, "not_found"
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    exp = str(meta.get("workspace_worker_token") or "").strip()
    if not exp:
        return None, "forbidden"
    if not secrets.compare_digest(exp, (token or "").strip()):
        return None, "unauthorized"
    return row, None


def merge_job_meta(conn: sqlite3.Connection, jid: str, patch: dict[str, Any]) -> bool:
    """Merge ``patch`` into the job's ``meta_json``."""
    row = get_job(conn, jid)
    if row is None:
        return False
    meta = dict(row.get("meta") or {})
    meta.update(patch)
    now = time.time()
    with _lock:
        conn.execute(
            "UPDATE jobs SET meta_json = ?, updated = ? WHERE id = ?",
            (json.dumps(meta), now, jid),
        )
        conn.commit()
    return True


def merge_worker_progress(conn: sqlite3.Connection, jid: str, body: dict[str, Any]) -> None:
    row = get_job(conn, jid)
    if row is None:
        raise ValueError("not_found")
    cur = dict(row["worker_progress"]) if isinstance(row.get("worker_progress"), dict) else {}
    if "pct" in body and body["pct"] is not None:
        try:
            cur["pct"] = int(body["pct"])
        except (TypeError, ValueError):
            pass
    if body.get("phase_label") is not None:
        cur["phase_label"] = str(body["phase_label"])[:200]
    if body.get("message") is not None:
        cur["message"] = str(body["message"])[:8000]
    cur["updated"] = time.time()
    now = time.time()
    with _lock:
        conn.execute(
            "UPDATE jobs SET worker_progress_json = ?, updated = ? WHERE id = ?",
            (json.dumps(cur), now, jid),
        )
        conn.commit()


def set_worker_result(conn: sqlite3.Connection, jid: str, body: dict[str, Any]) -> None:
    now = time.time()
    blob = json.dumps(body)[:1_500_000]
    with _lock:
        conn.execute(
            "UPDATE jobs SET worker_result_json = ?, updated = ? WHERE id = ?",
            (blob, now, jid),
        )
        conn.commit()


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


def count_running_jobs_by_container_class(conn: sqlite3.Connection) -> dict[str, int]:
    """Count ``running`` jobs by ``meta.container_class`` (missing → ``_none``)."""
    out: dict[str, int] = {}
    cur = conn.execute(
        "SELECT meta_json FROM jobs WHERE status = ?",
        ("running",),
    )
    for r in cur.fetchall():
        try:
            m = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            m = {}
        if not isinstance(m, dict):
            m = {}
        cc = str(m.get("container_class") or "").strip().lower()
        if not cc:
            cc = "_none"
        out[cc] = out.get(cc, 0) + 1
    return out


def workload_title_for_job(kind: str, session_id: str, meta: dict[str, Any]) -> str:
    """Short human label for admin tables (not a stable API contract)."""
    if not isinstance(meta, dict):
        meta = {}
    cc = str(meta.get("container_class") or "").strip().lower()
    sid = (session_id or "").strip()
    if cc == "host_cpu_probe":
        return "Test Fleet (host CPU probe)" if sid.startswith("test-fleet-") else "Host CPU probe"
    if cc == "empty":
        return "Empty container (internal)"
    if cc:
        return cc.replace("_", " ").strip().title()
    k = str(kind or "").strip().lower()
    if k == "docker_argv":
        return "Docker workload"
    return k or "Job"


def count_jobs(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()
    if row is None:
        return 0
    return int(row["n"] or 0)


def list_jobs_summary(conn: sqlite3.Connection, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 200))
    off = max(0, int(offset))
    cur = conn.execute(
        """
        SELECT id, kind, status, argv_json, meta_json, session_id, exit_code, container_id, created, updated
        FROM jobs
        ORDER BY updated DESC
        LIMIT ? OFFSET ?
        """,
        (lim, off),
    )
    rows: list[dict[str, Any]] = []
    for r in cur.fetchall():
        argv = json.loads(r["argv_json"] or "[]")
        preview = " ".join(str(x) for x in argv[:24])
        if len(preview) > 280:
            preview = preview[:280] + "…"
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        jid = str(r["id"] or "")
        id_short = (jid[:10] + "…") if len(jid) > 10 else jid
        sid = r["session_id"] or ""
        rows.append(
            {
                "id": jid,
                "id_short": id_short,
                "kind": r["kind"],
                "status": r["status"],
                "session_id": sid,
                "workload_title": workload_title_for_job(str(r["kind"] or ""), sid, meta),
                "argv_preview": preview,
                "exit_code": r["exit_code"],
                "container_id": r["container_id"],
                "created": r["created"],
                "updated": r["updated"],
            }
        )
    return rows


