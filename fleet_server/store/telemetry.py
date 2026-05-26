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

from fleet_server.store.core import (
    _ensure_cooldown_table,
    _ensure_energy_ledger,
    _ensure_telemetry_table,
    _lock,
)

def telemetry_time_bounds(conn: sqlite3.Connection) -> tuple[float | None, float | None, int]:
    """Return ``(min_ts, max_ts, row_count)`` for ``telemetry_samples`` (any missing -> None / 0)."""
    try:
        row = conn.execute(
            "SELECT MIN(ts) AS t0, MAX(ts) AS t1, COUNT(*) AS n FROM telemetry_samples"
        ).fetchone()
    except sqlite3.OperationalError:
        return None, None, 0
    if row is None or int(row["n"] or 0) == 0:
        return None, None, 0
    t0 = float(row["t0"]) if row["t0"] is not None else None
    t1 = float(row["t1"]) if row["t1"] is not None else None
    return t0, t1, int(row["n"] or 0)


def _telemetry_prune(conn: sqlite3.Connection) -> None:
    raw = str(os.environ.get("FLEET_TELEMETRY_RETENTION_DAYS") or "").strip()
    if not raw or raw == "0":
        return
    try:
        days = int(raw)
    except ValueError:
        return
    if days <= 0:
        return
    cutoff = time.time() - float(days) * 86400.0
    conn.execute("DELETE FROM telemetry_samples WHERE ts < ?", (cutoff,))


def _energy_ledger_row_to_public(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {
            "rapl_kwh": 0.0,
            "gpu_kwh": 0.0,
            "total_kwh": 0.0,
            "updated_epoch": None,
            "last_sample_epoch": None,
        }
    cr = float(row["cumulative_wh_rapl"] or 0.0)
    cg = float(row["cumulative_wh_gpu"] or 0.0)
    return {
        "rapl_kwh": round(cr / 1000.0, 9),
        "gpu_kwh": round(cg / 1000.0, 9),
        "total_kwh": round((cr + cg) / 1000.0, 9),
        "updated_epoch": float(row["updated"]) if row["updated"] is not None else None,
        "last_sample_epoch": float(row["last_ts"]) if row["last_ts"] is not None else None,
    }


def get_energy_ledger(conn: sqlite3.Connection) -> dict[str, Any]:
    """Cumulative kWh derived from RAPL package counters and NVIDIA ``power.draw`` (trapezoid over sample gaps)."""
    _ensure_energy_ledger(conn)
    row = conn.execute(
        "SELECT cumulative_wh_rapl, cumulative_wh_gpu, updated, last_ts FROM fleet_energy_ledger WHERE id = 1"
    ).fetchone()
    return _energy_ledger_row_to_public(row)


def apply_energy_ledger_delta(conn: sqlite3.Connection, ts: float, energy: dict[str, Any]) -> dict[str, float]:
    """
    Advance cumulative Wh from ``energy`` vs last sample, then return kWh totals
    (``rapl_kwh``, ``gpu_kwh``, ``total_kwh``).
    """
    _ensure_energy_ledger(conn)
    row = conn.execute("SELECT * FROM fleet_energy_ledger WHERE id = 1").fetchone()
    if row is None:
        return {"rapl_kwh": 0.0, "gpu_kwh": 0.0, "total_kwh": 0.0}
    cum_r = float(row["cumulative_wh_rapl"] or 0.0)
    cum_g = float(row["cumulative_wh_gpu"] or 0.0)
    last_ts = row["last_ts"]
    last_uj = row["last_rapl_uj"]
    last_gpu_w = row["last_gpu_power_w"]

    rapl_new = energy.get("rapl_package_uj")
    if rapl_new is not None and not isinstance(rapl_new, (int, float)):
        rapl_new = None
    if rapl_new is not None:
        rapl_new = float(rapl_new)

    gpu_new = energy.get("gpu_power_draw_w_sum")
    if gpu_new is not None and not isinstance(gpu_new, (int, float)):
        gpu_new = None
    if gpu_new is not None:
        gpu_new = float(gpu_new)

    if last_ts is None:
        conn.execute(
            """
            UPDATE fleet_energy_ledger SET
                last_ts = ?,
                last_rapl_uj = ?,
                last_gpu_power_w = ?,
                updated = ?
            WHERE id = 1
            """,
            (ts, rapl_new, gpu_new, ts),
        )
    else:
        dt = float(ts) - float(last_ts)
        if dt > 0 and rapl_new is not None and last_uj is not None:
            ln = float(last_uj)
            rn = float(rapl_new)
            if rn >= ln:
                cum_r += (rn - ln) / 3_600_000_000.0
        if dt > 0:
            g0 = float(last_gpu_w) if last_gpu_w is not None else None
            g1 = gpu_new
            if g0 is not None and g1 is not None:
                cum_g += (g0 + g1) * 0.5 * dt / 3600.0
            elif g1 is not None:
                cum_g += g1 * dt / 3600.0
            elif g0 is not None:
                cum_g += g0 * dt / 3600.0
        new_last_uj = rapl_new if rapl_new is not None else last_uj
        new_last_gpu = gpu_new if gpu_new is not None else last_gpu_w
        conn.execute(
            """
            UPDATE fleet_energy_ledger SET
                cumulative_wh_rapl = ?,
                cumulative_wh_gpu = ?,
                last_ts = ?,
                last_rapl_uj = ?,
                last_gpu_power_w = ?,
                updated = ?
            WHERE id = 1
            """,
            (cum_r, cum_g, ts, new_last_uj, new_last_gpu, ts),
        )

    return {
        "rapl_kwh": round(cum_r / 1000.0, 9),
        "gpu_kwh": round(cum_g / 1000.0, 9),
        "total_kwh": round((cum_r + cum_g) / 1000.0, 9),
    }


def maybe_record_telemetry_sample(
    conn: sqlite3.Connection,
    db_path: Path,
    host: dict[str, Any],
    orchestration: dict[str, Any] | None = None,
) -> bool:
    """
    Append one host snapshot row if the wall interval has elapsed (default 60s, ``FLEET_TELEMETRY_INTERVAL_S``).

    Throttle uses the latest row timestamp in ``telemetry_samples`` so separate processes (HTTP server vs
    ``fleet-telemetry-sample`` timer) share one cadence.

    Returns True when a row was written.
    """
    try:
        interval = float(os.environ.get("FLEET_TELEMETRY_INTERVAL_S") or "60")
    except ValueError:
        interval = 60.0
    interval = max(5.0, interval)
    now = time.time()
    with _lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            return False
        try:
            row = conn.execute("SELECT MAX(ts) AS m FROM telemetry_samples").fetchone()
            last_ts = float(row["m"]) if row and row["m"] is not None else None
            if last_ts is not None and (now - last_ts) < interval:
                conn.rollback()
                return False
            energy_in = host.get("energy") if isinstance(host.get("energy"), dict) else {}
            try:
                ledger = apply_energy_ledger_delta(conn, now, energy_in)
            except sqlite3.Error:
                ledger = None
            host_out = dict(host)
            e_out = dict(energy_in)
            if ledger is not None:
                e_out["cumulative_kwh"] = ledger
            host_out["energy"] = e_out
            orch = orchestration if isinstance(orchestration, dict) else {}
            payload_obj: dict[str, Any] = {"host": host_out, "orchestration": orch}
            payload = json.dumps(payload_obj, separators=(",", ":"), default=str)
            conn.execute(
                "INSERT INTO telemetry_samples (ts, payload_json) VALUES (?, ?)",
                (now, payload),
            )
            _telemetry_prune(conn)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise
    return True


def list_telemetry_samples(
    conn: sqlite3.Connection, *, t0: float, t1: float, limit: int
) -> tuple[list[dict[str, Any]], bool]:
    """
    Samples with ``t0 <= ts <= t1`` ascending by ``ts``.

    Returns ``(rows, truncated)`` where ``truncated`` is True when more rows existed than ``limit``.
    """
    lim = max(1, min(int(limit), 500_000))
    try:
        cur = conn.execute(
            "SELECT COUNT(*) AS c FROM telemetry_samples WHERE ts >= ? AND ts <= ?",
            (t0, t1),
        )
        total = int(cur.fetchone()["c"])
        cur = conn.execute(
            """
            SELECT ts, payload_json FROM telemetry_samples
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (t0, t1, lim),
        )
    except sqlite3.OperationalError:
        return [], False
    rows: list[dict[str, Any]] = []
    for r in cur.fetchall():
        try:
            raw = json.loads(r["payload_json"] or "{}")
        except json.JSONDecodeError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        if "host" in raw and isinstance(raw.get("host"), dict):
            host_payload: dict[str, Any] = raw["host"]
            orch = raw.get("orchestration")
            orch_out: dict[str, Any] = orch if isinstance(orch, dict) else {}
        else:
            host_payload = raw
            orch_out = {}
        rows.append({"ts": float(r["ts"]), "host": host_payload, "orchestration": orch_out})
    truncated = total > len(rows)
    return rows, truncated


def _cooldown_prune(conn: sqlite3.Connection) -> None:
    raw = str(os.environ.get("FLEET_TELEMETRY_RETENTION_DAYS") or "").strip()
    if not raw or raw == "0":
        return
    try:
        days = int(raw)
    except ValueError:
        return
    if days <= 0:
        return
    cutoff = time.time() - float(days) * 86400.0
    try:
        conn.execute("DELETE FROM fleet_cooldown_events WHERE ts < ?", (cutoff,))
    except sqlite3.OperationalError:
        pass


def insert_cooldown_event(
    conn: sqlite3.Connection,
    *,
    duration_s: float,
    ts: float | None = None,
    kind: str = "thermal_llm_guard",
    meta: dict[str, Any] | None = None,
) -> int:
    """
    Record one cooldown wait. ``ts`` is wall time when the wait **finished** (defaults to now).
    ``duration_s`` must be non-negative.
    """
    d = float(duration_s)
    if d < 0 or d != d:  # NaN
        raise ValueError("duration_s must be a non-negative number")
    now = float(ts) if ts is not None else time.time()
    meta_json = json.dumps(meta, separators=(",", ":"), default=str) if meta else None
    k = (kind or "thermal_llm_guard").strip() or "thermal_llm_guard"
    with _lock:
        cur = conn.execute(
            """
            INSERT INTO fleet_cooldown_events (ts, duration_s, kind, meta_json)
            VALUES (?, ?, ?, ?)
            """,
            (now, d, k, meta_json),
        )
        _cooldown_prune(conn)
        conn.commit()
        return int(cur.lastrowid or 0)


def cooldown_time_bounds(conn: sqlite3.Connection) -> tuple[float | None, float | None, int]:
    """``(min_ts, max_ts, row_count)`` for cooldown events."""
    try:
        row = conn.execute(
            "SELECT MIN(ts) AS t0, MAX(ts) AS t1, COUNT(*) AS n FROM fleet_cooldown_events"
        ).fetchone()
    except sqlite3.OperationalError:
        return None, None, 0
    if row is None or int(row["n"] or 0) == 0:
        return None, None, 0
    t0 = float(row["t0"]) if row["t0"] is not None else None
    t1 = float(row["t1"]) if row["t1"] is not None else None
    return t0, t1, int(row["n"] or 0)


def cooldown_aggregate_s(conn: sqlite3.Connection, *, t0: float, t1: float) -> tuple[float, int]:
    """``(sum(duration_s), event_count)`` for ``t0 <= ts <= t1``."""
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(duration_s), 0.0) AS s, COUNT(*) AS c
            FROM fleet_cooldown_events
            WHERE ts >= ? AND ts <= ?
            """,
            (t0, t1),
        ).fetchone()
    except sqlite3.OperationalError:
        return 0.0, 0
    if row is None:
        return 0.0, 0
    s = float(row["s"] or 0.0)
    c = int(row["c"] or 0)
    return s, c


def cooldown_summary_payload(conn: sqlite3.Connection, *, period: str) -> dict[str, Any]:
    """Single-period summary for ``GET /v1/cooldown-summary``."""
    t_min, t_max, n_ev = cooldown_time_bounds(conn)
    period_key = telemetry_periods.PERIOD_ALIASES.get(period, period)
    t0, t1 = telemetry_periods.resolve_period_window(period_key, first_sample_ts=t_min)
    total_s, count = cooldown_aggregate_s(conn, t0=t0, t1=t1)
    return {
        "ok": True,
        "period": period_key,
        "period_requested": period,
        "timezone": "UTC",
        "window": {"start_epoch": t0, "end_epoch": t1},
        "total_cooldown_s": round(total_s, 6),
        "event_count": count,
        "store_bounds": {"first_ts": t_min, "last_ts": t_max if n_ev else None},
    }


def cooldown_summary_presets(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Preset windows for admin UI: today, this_week, this_month, this_year, since_first.

    Keys match :func:`telemetry_periods.resolve_period_window` where applicable.
    """
    t_min, t_max, n = cooldown_time_bounds(conn)
    presets = ("today", "this_week", "this_month", "this_year", "since_first")
    out: dict[str, Any] = {}
    for key in presets:
        try:
            t0, t1 = telemetry_periods.resolve_period_window(key, first_sample_ts=t_min)
        except ValueError:
            continue
        total_s, count = cooldown_aggregate_s(conn, t0=t0, t1=t1)
        out[key] = {
            "window": {"start_epoch": t0, "end_epoch": t1},
            "total_cooldown_s": round(total_s, 6),
            "event_count": count,
        }
    out["_store"] = {"first_ts": t_min, "last_ts": t_max, "event_count": n}
    return out
