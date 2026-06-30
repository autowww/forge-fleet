"""Telemetry 5m rollup buckets + gap backfill."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fleet_server import store, telemetry_rollup, versioning


def _host(cpu: float, *, ts_offset: float = 0.0) -> dict:
    return {
        "cpu_usage_pct": cpu,
        "memory": {"used_pct": 50.0},
        "thermal": {"max_c": 60.0 + cpu},
        "cpus": 8,
        "loadavg": [1.0, 1.0, 1.0],
        "disks": {"space": [{"used_pct": 40.0}], "io": {"available": False}},
    }


def test_rollup_tables_on_connect(tmp_path: Path) -> None:
    db = tmp_path / "r.sqlite"
    conn = store.connect(db)
    try:
        row = store.get_fleet_version_row(conn)
        assert int(row["db_schema_version"]) == int(versioning.FLEET_DB_SCHEMA_VERSION)
        conn.execute("SELECT bucket_start FROM telemetry_buckets_5m LIMIT 1")
    finally:
        conn.close()


def _insert_sample(conn, db: Path, ts: float, cpu: float) -> None:
    import json

    payload = json.dumps({"host": _host(cpu), "orchestration": {}}, separators=(",", ":"))
    conn.execute("INSERT INTO telemetry_samples (ts, payload_json) VALUES (?, ?)", (ts, payload))
    conn.commit()


def test_compute_and_finalize_bucket(tmp_path: Path) -> None:
    db = tmp_path / "b.sqlite"
    conn = store.connect(db)
    try:
        _insert_sample(conn, db, 1_000.0, 10.0)
        _insert_sample(conn, db, 1_006.0, 20.0)
        bs = telemetry_rollup.align_bucket_start(1_000.0)
        bucket = telemetry_rollup.compute_5m_bucket(conn, bs)
        assert bucket is not None
        assert bucket["sample_count"] == 2
        assert abs(float(bucket["cpu_avg"] or 0) - 15.0) < 1e-6
        n = telemetry_rollup.finalize_closed_buckets(conn, now=1_400.0, max_buckets=10)
        assert n >= 1
        rows = telemetry_rollup.list_5m_buckets(conn, t0=bs, t1=bs + 300)
        assert len(rows) == 1
        assert rows[0]["cpu"] == pytest.approx(15.0, abs=1e-6)
    finally:
        conn.close()


def test_backfill_gaps(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    t0 = 10_000.0
    conn = store.connect(db)
    try:
        _insert_sample(conn, db, t0, 5.0)
        _insert_sample(conn, db, t0 + 6, 7.0)
        _insert_sample(conn, db, t0 + 900, 30.0)
        _insert_sample(conn, db, t0 + 906, 40.0)
        assert telemetry_rollup.gaps_remain(conn, now=t0 + 1200)
        n = telemetry_rollup.backfill_missing_buckets(conn, now=t0 + 1200, max_buckets=50)
        assert n == 2
        assert not telemetry_rollup.gaps_remain(conn, now=t0 + 1200)
    finally:
        conn.close()


def test_chart_buckets_for_period(tmp_path: Path) -> None:
    db = tmp_path / "c.sqlite"
    base = 20_000.0
    conn = store.connect(db)
    try:
        for i in range(6):
            _insert_sample(conn, db, base + i * 300, float(i))
        telemetry_rollup.backfill_missing_buckets(conn, now=base + 3600, max_buckets=100)
        buckets, bucket_ms, source = telemetry_rollup.chart_buckets_for_period(
            conn,
            period_key="last_24_hours",
            t0=base,
            t1=base + 3600,
        )
        assert source == "telemetry_buckets_5m"
        assert bucket_ms == 300_000.0
        assert len(buckets) >= 1
    finally:
        conn.close()
