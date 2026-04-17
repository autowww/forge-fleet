"""Telemetry samples table + period windows + query API helpers."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fleet_server import store, telemetry_periods, versioning


def test_telemetry_table_created(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    conn = store.connect(db)
    try:
        row = store.get_fleet_version_row(conn)
        assert int(row["db_schema_version"]) == int(versioning.FLEET_DB_SCHEMA_VERSION)
        t0, t1, n = store.telemetry_time_bounds(conn)
        assert t0 is None and t1 is None and n == 0
    finally:
        conn.close()


def test_record_and_query(tmp_path: Path) -> None:
    db = tmp_path / "u.sqlite"
    conn = store.connect(db)
    try:
        host = {"cpu_usage_pct": 12.3, "time_utc": "x"}
        assert store.maybe_record_telemetry_sample(conn, db, host) is True
        assert store.maybe_record_telemetry_sample(conn, db, host) is False
        t0, t1, n = store.telemetry_time_bounds(conn)
        assert n == 1
        assert t0 is not None and t1 is not None
        rows, trunc = store.list_telemetry_samples(conn, t0=t0 - 1, t1=t1 + 1, limit=10)
        assert not trunc
        assert len(rows) == 1
        assert rows[0]["host"]["cpu_usage_pct"] == 12.3
    finally:
        conn.close()


def test_resolve_last_hour_bounds() -> None:
    anchor = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    t0, t1 = telemetry_periods.resolve_period_window("last_1_hour", now=anchor, first_sample_ts=None)
    assert t1 == anchor.timestamp()
    assert abs(t0 - (anchor - timedelta(hours=1)).timestamp()) < 1e-6


def test_resolve_since_first() -> None:
    anchor = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    t0, t1 = telemetry_periods.resolve_period_window(
        "since_first",
        now=anchor,
        first_sample_ts=1000.0,
    )
    assert t0 == 1000.0
    assert t1 == anchor.timestamp()


def test_energy_ledger_rapl_delta(tmp_path: Path) -> None:
    db = tmp_path / "e.sqlite"
    conn = store.connect(db)
    try:
        r0 = store.apply_energy_ledger_delta(conn, 1_000.0, {"rapl_package_uj": 1_000_000_000.0})
        assert r0["rapl_kwh"] == 0.0
        conn.commit()
        # +360e6 µJ == 0.1 Wh == 1e-4 kWh
        r1 = store.apply_energy_ledger_delta(conn, 1_060.0, {"rapl_package_uj": 1_360_000_000.0})
        assert abs(r1["rapl_kwh"] - 1.0e-4) < 1e-12
        assert r1["gpu_kwh"] == 0.0
        pub = store.get_energy_ledger(conn)
        assert abs(pub["rapl_kwh"] - 1.0e-4) < 1e-12
        assert pub["last_sample_epoch"] == 1_060.0
    finally:
        conn.close()


def test_energy_ledger_gpu_trapezoid(tmp_path: Path) -> None:
    db = tmp_path / "g.sqlite"
    conn = store.connect(db)
    try:
        store.apply_energy_ledger_delta(conn, 0.0, {"gpu_power_draw_w_sum": 120.0})
        conn.commit()
        r = store.apply_energy_ledger_delta(conn, 3_600.0, {"gpu_power_draw_w_sum": 120.0})
        # avg 120 W over 1 h => 120 Wh => 0.12 kWh
        assert abs(r["gpu_kwh"] - 0.12) < 1e-9
    finally:
        conn.close()


def test_telemetry_sample_includes_cumulative_kwh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "k.sqlite"
    clock = itertools.chain([1000.0, 1006.0, 1012.0], itertools.repeat(50_000.0))
    monkeypatch.setattr(store.time, "time", lambda: next(clock))
    monkeypatch.setenv("FLEET_TELEMETRY_INTERVAL_S", "5")
    conn = store.connect(db)
    try:
        uj0 = 10_000_000_000_000  # 10^13 µJ baseline (same order as real RAPL counters)
        h = {"cpu_usage_pct": 1.0, "energy": {"rapl_package_uj": float(uj0)}}
        assert store.maybe_record_telemetry_sample(conn, db, h) is True
        h2 = {"cpu_usage_pct": 2.0, "energy": {"rapl_package_uj": float(uj0 + 3_600_000_000)}}
        assert store.maybe_record_telemetry_sample(conn, db, h2) is True
        t0, t1, _n = store.telemetry_time_bounds(conn)
        rows, _ = store.list_telemetry_samples(conn, t0=t0 - 1, t1=t1 + 1, limit=10)
        assert rows[0]["host"]["energy"]["cumulative_kwh"]["rapl_kwh"] == 0.0
        assert abs(rows[1]["host"]["energy"]["cumulative_kwh"]["rapl_kwh"] - 0.001) < 1e-12
    finally:
        conn.close()
