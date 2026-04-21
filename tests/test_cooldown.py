"""Cooldown events table and aggregation API helpers."""

from __future__ import annotations

import time
from pathlib import Path

from fleet_server import store, versioning


def test_cooldown_table_and_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "c.sqlite"
    conn = store.connect(db)
    try:
        row = store.get_fleet_version_row(conn)
        assert int(row["db_schema_version"]) == int(versioning.FLEET_DB_SCHEMA_VERSION)
        t0, t1, n = store.cooldown_time_bounds(conn)
        assert t0 is None and t1 is None and n == 0
    finally:
        conn.close()


def test_insert_aggregate_and_presets(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    now = time.time()
    conn = store.connect(db)
    try:
        store.insert_cooldown_event(conn, duration_s=1.5, ts=now - 3600, kind="thermal_llm_guard")
        store.insert_cooldown_event(conn, duration_s=2.5, ts=now - 10, kind="thermal_llm_guard")
        tot, cnt = store.cooldown_aggregate_s(conn, t0=now - 7200, t1=now + 1)
        assert cnt == 2
        assert abs(tot - 4.0) < 1e-6
        presets = store.cooldown_summary_presets(conn)
        assert "today" in presets
        assert "since_first" in presets
        assert presets["since_first"]["event_count"] == 2
        assert presets["since_first"]["total_cooldown_s"] >= 4.0 - 1e-5
    finally:
        conn.close()


def test_cooldown_summary_payload_period(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    conn = store.connect(db)
    try:
        p = store.cooldown_summary_payload(conn, period="today")
        assert p.get("ok") is True
        assert "total_cooldown_s" in p
        assert "event_count" in p
    finally:
        conn.close()
