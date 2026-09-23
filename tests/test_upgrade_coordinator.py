"""Tests for upgrade coordinator."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import lifecycle, upgrade_coordinator


def test_wait_for_readiness_abort(tmp_path: Path) -> None:
    lifecycle.mark_startup_ready()
    lifecycle.resume()
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    lifecycle.proxy_enter()
    try:
        out = upgrade_coordinator.wait_for_readiness(
            db,
            tmp_path,
            max_wait_sec=1,
            on_timeout="abort",
            upgrade_id="test-u1",
        )
        assert out["ok"] is False
        assert out["error"] == "upgrade_blocked"
    finally:
        lifecycle.proxy_exit()


def test_wait_for_readiness_force(tmp_path: Path) -> None:
    lifecycle.mark_startup_ready()
    lifecycle.resume()
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    lifecycle.proxy_enter()
    try:
        out = upgrade_coordinator.wait_for_readiness(
            db,
            tmp_path,
            max_wait_sec=1,
            on_timeout="force",
            upgrade_id="test-u2",
        )
        assert out["ok"] is True
        assert out.get("forced") is True
    finally:
        lifecycle.proxy_exit()


def test_aggregate_readiness_fleet_only(tmp_path: Path) -> None:
    lifecycle.mark_startup_ready()
    lifecycle.resume()
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    with patch("fleet_server.upgrade_coordinator.list_dependents", return_value=[]):
        agg = upgrade_coordinator.aggregate_readiness(db, tmp_path)
    assert agg["stop_allowed"] is True
