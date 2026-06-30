"""Pre-aggregate telemetry samples into fixed 5-minute SQLite buckets."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import store

BUCKET_5M_S = 300.0
DISK_IO_REF_MBPS = 600.0
_BUCKET_START_SQL = "(CAST(ts / 300.0 AS INTEGER) * 300.0)"
_BUCKET_START_SQL_S = "(CAST(s.ts / 300.0 AS INTEGER) * 300.0)"

_backfill_lock = threading.Lock()
_backfill_running = False

# Chart rebucketing for periods longer than 24h (mirrors admin.html NICE_BUCKET_MS).
NICE_BUCKET_MS: tuple[float, ...] = (
    60_000,
    120_000,
    180_000,
    300_000,
    600_000,
    900_000,
    1_200_000,
    1_800_000,
    3_600_000,
    7_200_000,
    10_800_000,
    14_400_000,
    21_600_000,
    28_800_000,
    43_200_000,
    86_400_000,
    172_800_000,
    604_800_000,
)


def align_bucket_start(ts: float) -> float:
    """UTC wall-clock 5-minute bucket start (epoch seconds)."""
    return float(int(ts // BUCKET_5M_S) * int(BUCKET_5M_S))


def host_metrics_for_chart(host: dict[str, Any]) -> dict[str, float | None]:
    """Extract chart scalars from a host snapshot (matches admin.html defaults)."""
    cpu_raw = host.get("cpu_usage_pct")
    cpu = (
        min(100.0, max(0.0, float(cpu_raw)))
        if cpu_raw is not None and float(cpu_raw) == float(cpu_raw)
        else 0.0
    )
    mem_h = host.get("memory") if isinstance(host.get("memory"), dict) else {}
    mem_raw = mem_h.get("used_pct")
    mem = (
        min(100.0, max(0.0, float(mem_raw)))
        if mem_raw is not None and float(mem_raw) == float(mem_raw)
        else 0.0
    )
    temp_c = _host_thermal_max_c(host)
    load_pct = _host_load_pct1(host)
    disk_ui = _disk_primary_pct(host)
    return {
        "cpu": cpu,
        "mem": mem,
        "temp_c": temp_c,
        "load_pct": load_pct,
        "disk_ui": disk_ui,
    }


def _host_thermal_max_c(host: dict[str, Any]) -> float | None:
    th = host.get("thermal") if isinstance(host.get("thermal"), dict) else {}
    mc = th.get("max_c")
    cpu_ok = mc is not None and float(mc) == float(mc)
    cpu_v = float(mc) if cpu_ok else None
    gpu = host.get("gpu") if isinstance(host.get("gpu"), dict) else {}
    gn = gpu.get("nvidia") if isinstance(gpu.get("nvidia"), dict) else {}
    gpu_max: float | None = None
    if gn.get("available") and isinstance(gn.get("devices"), list):
        temps: list[float] = []
        for dev in gn["devices"]:
            if isinstance(dev, dict) and dev.get("temperature_c") is not None:
                t = float(dev["temperature_c"])
                if t == t:
                    temps.append(t)
        if temps:
            gpu_max = max(temps)
    if cpu_v is not None and gpu_max is not None:
        return max(cpu_v, gpu_max)
    if cpu_v is not None:
        return cpu_v
    return gpu_max


def _host_load_pct1(host: dict[str, Any]) -> float | None:
    la = host.get("loadavg")
    if not isinstance(la, list) or len(la) < 1:
        return None
    try:
        l1 = float(la[0])
    except (TypeError, ValueError):
        return None
    if l1 != l1:
        return None
    cpus_raw = host.get("cpus")
    try:
        cpus = float(cpus_raw)
    except (TypeError, ValueError):
        cpus = 1.0
    den = cpus if cpus >= 1.0 else 1.0
    return min(100.0, max(0.0, (100.0 * l1) / den))


def _disk_primary_pct(host: dict[str, Any]) -> float | None:
    disks = host.get("disks") if isinstance(host.get("disks"), dict) else {}
    space = disks.get("space") if isinstance(disks.get("space"), list) else []
    max_u: float | None = None
    for row in space:
        if not isinstance(row, dict):
            continue
        u = row.get("used_pct")
        if u is None or float(u) != float(u):
            continue
        nu = float(u)
        max_u = nu if max_u is None else max(max_u, nu)
    io = disks.get("io") if isinstance(disks.get("io"), dict) else {}
    io_agg = io.get("aggregated") if io.get("available") is True and isinstance(io.get("aggregated"), dict) else None
    busy: float | None = None
    if io_agg and io_agg.get("busy_pct_est_max") is not None:
        b = float(io_agg["busy_pct_est_max"])
        if b == b:
            busy = b
    if busy is not None:
        return busy
    if io_agg and io_agg.get("total_mbps") is not None:
        m = float(io_agg["total_mbps"])
        if m == m and m >= 0:
            return min(100.0, max(0.0, (m / DISK_IO_REF_MBPS) * 100.0))
    return max_u


def ensure_rollup_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_buckets_5m (
            bucket_start REAL NOT NULL PRIMARY KEY,
            sample_count INTEGER NOT NULL DEFAULT 0,
            cpu_avg REAL,
            mem_avg REAL,
            temp_c_avg REAL,
            load_pct_avg REAL,
            disk_ui_avg REAL,
            computed_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_telemetry_buckets_5m_start ON telemetry_buckets_5m (bucket_start)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry_rollup_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_backfill_bucket REAL,
            updated REAL NOT NULL DEFAULT 0
        )
        """
    )
    row = conn.execute("SELECT id FROM telemetry_rollup_state WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO telemetry_rollup_state (id, last_backfill_bucket, updated) VALUES (1, NULL, 0)"
        )


def _avg(vals: list[float]) -> float | None:
    if not vals:
        return None
    return sum(vals) / len(vals)


def compute_5m_bucket(conn: sqlite3.Connection, bucket_start: float) -> dict[str, Any] | None:
    """Average raw samples in ``[bucket_start, bucket_start + 5m)``; None when empty."""
    t0 = float(bucket_start)
    t1 = t0 + BUCKET_5M_S
    rows, _trunc = store.list_telemetry_samples(conn, t0=t0, t1=t1 - 1e-9, limit=10_000)
    cpus: list[float] = []
    mems: list[float] = []
    temps: list[float] = []
    loads: list[float] = []
    disks: list[float] = []
    count = 0
    for row in rows:
        ts = float(row.get("ts") or 0)
        if ts < t0 or ts >= t1:
            continue
        host = row.get("host") if isinstance(row.get("host"), dict) else {}
        met = host_metrics_for_chart(host)
        count += 1
        cpus.append(float(met["cpu"] or 0.0))
        mems.append(float(met["mem"] or 0.0))
        if met["temp_c"] is not None:
            temps.append(float(met["temp_c"]))
        if met["load_pct"] is not None:
            loads.append(float(met["load_pct"]))
        if met["disk_ui"] is not None:
            disks.append(float(met["disk_ui"]))
    if count <= 0:
        return None
    now = time.time()
    return {
        "bucket_start": t0,
        "sample_count": count,
        "cpu_avg": _avg(cpus),
        "mem_avg": _avg(mems),
        "temp_c_avg": _avg(temps),
        "load_pct_avg": _avg(loads),
        "disk_ui_avg": _avg(disks),
        "computed_at": now,
    }


def upsert_5m_bucket(conn: sqlite3.Connection, bucket: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO telemetry_buckets_5m
            (bucket_start, sample_count, cpu_avg, mem_avg, temp_c_avg, load_pct_avg, disk_ui_avg, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bucket_start) DO UPDATE SET
            sample_count = excluded.sample_count,
            cpu_avg = excluded.cpu_avg,
            mem_avg = excluded.mem_avg,
            temp_c_avg = excluded.temp_c_avg,
            load_pct_avg = excluded.load_pct_avg,
            disk_ui_avg = excluded.disk_ui_avg,
            computed_at = excluded.computed_at
        """,
        (
            float(bucket["bucket_start"]),
            int(bucket["sample_count"]),
            bucket.get("cpu_avg"),
            bucket.get("mem_avg"),
            bucket.get("temp_c_avg"),
            bucket.get("load_pct_avg"),
            bucket.get("disk_ui_avg"),
            float(bucket["computed_at"]),
        ),
    )


def materialize_5m_bucket(conn: sqlite3.Connection, bucket_start: float, *, now: float | None = None) -> dict[str, Any] | None:
    """Compute averages from samples; None when the bucket has no raw samples."""
    del now
    return compute_5m_bucket(conn, bucket_start)


def _last_closed_bucket_start(now: float) -> float:
    """Latest fully elapsed 5m bucket start."""
    return align_bucket_start(now - BUCKET_5M_S)


def finalize_closed_buckets(conn: sqlite3.Connection, *, now: float | None = None, max_buckets: int = 48) -> int:
    """Compute and store closed buckets not yet present (or stale open edge)."""
    now_f = float(now if now is not None else time.time())
    closed_end = _last_closed_bucket_start(now_f)
    try:
        row = conn.execute("SELECT MAX(bucket_start) AS m FROM telemetry_buckets_5m").fetchone()
        last_stored = float(row["m"]) if row and row["m"] is not None else None
    except sqlite3.OperationalError:
        return 0
    if last_stored is None:
        t_min, _t_max, n = store.telemetry_time_bounds(conn)
        if t_min is None or n <= 0:
            return 0
        start = align_bucket_start(float(t_min))
    else:
        start = last_stored + BUCKET_5M_S
    written = 0
    lim = max(1, int(max_buckets))
    bs = start
    while bs <= closed_end and written < lim:
        bucket = materialize_5m_bucket(conn, bs, now=now_f)
        if bucket is not None:
            upsert_5m_bucket(conn, bucket)
            written += 1
        bs += BUCKET_5M_S
    if written:
        conn.execute(
            "UPDATE telemetry_rollup_state SET last_backfill_bucket = ?, updated = ? WHERE id = 1",
            (min(bs - BUCKET_5M_S, closed_end), now_f),
        )
        conn.commit()
    return written


def _missing_bucket_starts_sql(
    conn: sqlite3.Connection, *, t0: float, t1: float, closed_end: float, limit: int
) -> list[float]:
    """Bucket starts that have raw samples but no rollup row (SQL, bounded)."""
    try:
        cur = conn.execute(
            f"""
            WITH needed AS (
                SELECT DISTINCT {_BUCKET_START_SQL} AS bucket_start
                FROM telemetry_samples
                WHERE ts >= ? AND ts <= ?
            )
            SELECT bucket_start FROM needed
            WHERE bucket_start <= ?
              AND bucket_start NOT IN (
                SELECT bucket_start FROM telemetry_buckets_5m
                WHERE bucket_start >= ? AND bucket_start <= ?
              )
            ORDER BY bucket_start ASC
            LIMIT ?
            """,
            (float(t0), float(t1), float(closed_end), float(t0), float(closed_end), max(1, int(limit))),
        )
    except sqlite3.OperationalError:
        return []
    return [float(r["bucket_start"]) for r in cur.fetchall()]


def _rollup_gaps_remain(conn: sqlite3.Connection, *, now: float | None = None) -> bool:
    now_f = float(now if now is not None else time.time())
    t_min, t_max, n = store.telemetry_time_bounds(conn)
    if t_min is None or n <= 0:
        return False
    last = _last_closed_bucket_start(now_f)
    if last < align_bucket_start(float(t_min)):
        return False
    try:
        row = conn.execute(
            f"""
            SELECT 1
            FROM telemetry_samples s
            WHERE s.ts >= ? AND s.ts <= ?
              AND {_BUCKET_START_SQL} <= ?
              AND NOT EXISTS (
                SELECT 1 FROM telemetry_buckets_5m b
                WHERE b.bucket_start = {_BUCKET_START_SQL_S}
              )
            LIMIT 1
            """,
            (float(t_min), min(float(t_max), last + BUCKET_5M_S), last),
        ).fetchone()
    except sqlite3.OperationalError:
        return True
    return row is not None


def backfill_missing_buckets(conn: sqlite3.Connection, *, now: float | None = None, max_buckets: int = 400) -> int:
    """One-shot gap fill for 5m buckets that have raw samples but no rollup row."""
    now_f = float(now if now is not None else time.time())
    t_min, t_max, n = store.telemetry_time_bounds(conn)
    if t_min is None or n <= 0:
        return 0
    last = _last_closed_bucket_start(now_f)
    missing = _missing_bucket_starts_sql(
        conn,
        t0=float(t_min),
        t1=min(float(t_max), last + BUCKET_5M_S),
        closed_end=last,
        limit=max_buckets,
    )
    written = 0
    for bs in missing:
        bucket = materialize_5m_bucket(conn, bs, now=now_f)
        if bucket is not None:
            upsert_5m_bucket(conn, bucket)
            written += 1
    if written:
        conn.execute(
            "UPDATE telemetry_rollup_state SET last_backfill_bucket = ?, updated = ? WHERE id = 1",
            (missing[-1] if missing else last, now_f),
        )
        conn.commit()
    return written


def finalize_telemetry_rollup(
    conn: sqlite3.Connection,
    *,
    now: float | None = None,
    max_buckets: int = 8,
) -> int:
    """Fast path: close recent 5m buckets only (safe on hot request paths)."""
    ensure_rollup_tables(conn)
    return finalize_closed_buckets(conn, now=now, max_buckets=max_buckets)


def maybe_run_telemetry_rollup(
    conn: sqlite3.Connection,
    db_path: Path | str,
    *,
    now: float | None = None,
    finalize_limit: int = 8,
) -> dict[str, int | bool]:
    """Finalize recent buckets; schedule heavy backfill in background when needed."""
    finalized = finalize_telemetry_rollup(conn, now=now, max_buckets=finalize_limit)
    gaps = _rollup_gaps_remain(conn, now=now)
    if gaps:
        request_background_backfill(db_path)
    return {"finalized": finalized, "backfilled": 0, "gaps_remain": gaps}


def request_background_backfill(db_path: Path | str | None, *, batch_size: int = 500) -> bool:
    """Start one background backfill worker when gaps exist (no-op if already running)."""
    global _backfill_running
    with _backfill_lock:
        if _backfill_running:
            return False
        _backfill_running = True

    def _worker() -> None:
        global _backfill_running
        try:
            if db_path is None:
                return
            conn = store.connect(Path(db_path))
            try:
                run_full_backfill(conn, batch_size=batch_size)
            finally:
                conn.close()
        except (OSError, RuntimeError, sqlite3.Error):
            pass
        finally:
            with _backfill_lock:
                _backfill_running = False

    if db_path is None:
        with _backfill_lock:
            _backfill_running = False
        return False
    threading.Thread(target=_worker, name="fleet-telemetry-backfill", daemon=True).start()
    return True


def run_full_backfill(conn: sqlite3.Connection, *, batch_size: int = 500) -> int:
    """Backfill until no gaps remain (CLI / startup)."""
    ensure_rollup_tables(conn)
    total = 0
    while True:
        n = backfill_missing_buckets(conn, max_buckets=batch_size)
        finalize_closed_buckets(conn, max_buckets=batch_size)
        if n <= 0 and not _rollup_gaps_remain(conn):
            break
        total += n
        if n <= 0:
            break
    return total


def prune_old_buckets(conn: sqlite3.Connection) -> None:
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
    bucket_cutoff = align_bucket_start(cutoff)
    try:
        conn.execute("DELETE FROM telemetry_buckets_5m WHERE bucket_start < ?", (bucket_cutoff,))
    except sqlite3.OperationalError:
        pass


def list_5m_buckets(conn: sqlite3.Connection, *, t0: float, t1: float) -> list[dict[str, Any]]:
    try:
        cur = conn.execute(
            """
            SELECT bucket_start, sample_count, cpu_avg, mem_avg, temp_c_avg, load_pct_avg, disk_ui_avg
            FROM telemetry_buckets_5m
            WHERE bucket_start >= ? AND bucket_start <= ?
            ORDER BY bucket_start ASC
            """,
            (align_bucket_start(t0), align_bucket_start(t1)),
        )
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in cur.fetchall():
        if int(r["sample_count"] or 0) <= 0:
            continue
        bs = float(r["bucket_start"])
        center_ms = (bs + BUCKET_5M_S / 2.0) * 1000.0
        out.append(
            {
                "t": center_ms,
                "cpu": float(r["cpu_avg"] or 0.0),
                "mem": float(r["mem_avg"] or 0.0),
                "tempC": float(r["temp_c_avg"]) if r["temp_c_avg"] is not None else None,
                "loadPct": float(r["load_pct_avg"]) if r["load_pct_avg"] is not None else None,
                "diskUi": float(r["disk_ui_avg"]) if r["disk_ui_avg"] is not None else None,
                "sample_count": int(r["sample_count"] or 0),
                "bucket_start_epoch": bs,
            }
        )
    return out


def pick_nice_bucket_ms(window_ms: float, inner_width_px: float = 556.0) -> float:
    iw = inner_width_px if inner_width_px > 0 else 556.0
    target = round(iw / 46.0)
    target = max(24, min(160, target))
    ideal = window_ms / max(1.0, float(target))
    best = float(NICE_BUCKET_MS[len(NICE_BUCKET_MS) // 2])
    best_score = float("inf")
    for step in NICE_BUCKET_MS:
        nb = window_ms / step
        if nb > 220 or nb < 6:
            continue
        lo = ideal * 0.65
        hi = ideal * 1.75
        score = lo - step if step < lo else step - hi if step > hi else abs(step - ideal)
        if score < best_score:
            best_score = score
            best = step
    if best_score < float("inf"):
        return best
    for step in NICE_BUCKET_MS:
        nbb = window_ms / step
        if nbb <= 220 and nbb >= 3:
            return step
    return 3_600_000.0


def rebucket_metric_rows(
    rows: list[dict[str, Any]],
    *,
    bucket_ms: float,
    window_start_ms: float,
    window_end_ms: float,
) -> list[dict[str, Any]]:
    """Average rows into wall-clock buckets (mirrors admin.html)."""
    if bucket_ms <= 0 or window_end_ms <= window_start_ms:
        return []
    buckets: dict[int, dict[str, Any]] = {}

    def add_sum(bk: int, key: str, val: float | None) -> None:
        if val is None or val != val:
            return
        slot = buckets.setdefault(bk, {"sums": {}, "counts": {}})
        sums: dict[str, float] = slot["sums"]
        counts: dict[str, int] = slot["counts"]
        sums[key] = sums.get(key, 0.0) + float(val)
        counts[key] = counts.get(key, 0) + 1

    max_bk = int((window_end_ms - window_start_ms) / bucket_ms)
    for row in rows:
        t = row.get("t")
        if t is None or float(t) != float(t):
            continue
        t_f = float(t)
        if t_f < window_start_ms or t_f > window_end_ms:
            continue
        bk = int((t_f - window_start_ms) // bucket_ms)
        if bk < 0 or bk > max_bk + 1:
            continue
        add_sum(bk, "cpu", row.get("cpu"))
        add_sum(bk, "mem", row.get("mem"))
        add_sum(bk, "tempC", row.get("tempC"))
        add_sum(bk, "loadPct", row.get("loadPct"))
        add_sum(bk, "diskUi", row.get("diskUi"))

    out: list[dict[str, Any]] = []
    for bki in sorted(buckets.keys()):
        slot = buckets[bki]
        sums = slot["sums"]
        counts = slot["counts"]
        center = window_start_ms + bki * bucket_ms + bucket_ms / 2.0

        def avg(k: str) -> float | None:
            cnt = counts.get(k, 0)
            if not cnt:
                return None
            return sums[k] / cnt

        out.append(
            {
                "t": center,
                "cpu": avg("cpu") if avg("cpu") is not None else 0.0,
                "mem": avg("mem") if avg("mem") is not None else 0.0,
                "tempC": avg("tempC"),
                "loadPct": avg("loadPct"),
                "diskUi": avg("diskUi"),
            }
        )
    return out


def chart_buckets_for_period(
    conn: sqlite3.Connection,
    *,
    period_key: str,
    t0: float,
    t1: float,
) -> tuple[list[dict[str, Any]], float, str]:
    """
    Return chart-ready bucket rows, bucket size in ms, and source label.

    Uses stored 5m rollups; rebuckets for periods longer than 24h.
    """
    base = list_5m_buckets(conn, t0=t0, t1=t1)
    window_start_ms = t0 * 1000.0
    window_end_ms = t1 * 1000.0
    if period_key == "last_24_hours":
        bucket_ms = 300_000.0
        return rebucket_metric_rows(
            base, bucket_ms=bucket_ms, window_start_ms=window_start_ms, window_end_ms=window_end_ms
        ), bucket_ms, "telemetry_buckets_5m"
    bucket_ms = pick_nice_bucket_ms(window_end_ms - window_start_ms)
    return (
        rebucket_metric_rows(
            base, bucket_ms=bucket_ms, window_start_ms=window_start_ms, window_end_ms=window_end_ms
        ),
        bucket_ms,
        "telemetry_buckets_5m",
    )


def gaps_remain(conn: sqlite3.Connection, *, now: float | None = None) -> bool:
    return _rollup_gaps_remain(conn, now=now)


def rollup_state_public(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        row = conn.execute(
            "SELECT last_backfill_bucket, updated FROM telemetry_rollup_state WHERE id = 1"
        ).fetchone()
        count_row = conn.execute("SELECT COUNT(*) AS c FROM telemetry_buckets_5m").fetchone()
    except sqlite3.OperationalError:
        return {"bucket_count": 0, "gaps_remain": False}
    gaps = _rollup_gaps_remain(conn)
    return {
        "bucket_count": int(count_row["c"] or 0) if count_row else 0,
        "last_backfill_bucket": float(row["last_backfill_bucket"])
        if row and row["last_backfill_bucket"] is not None
        else None,
        "updated": float(row["updated"]) if row and row["updated"] is not None else None,
        "gaps_remain": gaps,
    }
