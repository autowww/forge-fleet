"""Tests for fleet_server.lifecycle."""

from __future__ import annotations

from pathlib import Path

from fleet_server import lifecycle, store


def test_stop_readiness_idle(tmp_path: Path) -> None:
    lifecycle.mark_startup_ready()
    lifecycle.resume()
    db = tmp_path / "fleet.db"
    store.connect(db).close()
    payload = lifecycle.stop_readiness_payload(db, tmp_path)
    assert payload["ok"] is True
    assert payload["stop_allowed"] is True
    assert payload["service_id"] == "forge-fleet"


def test_prepare_stop_sets_draining(tmp_path: Path) -> None:
    lifecycle.resume()
    out = lifecycle.prepare_stop({"upgrade_id": "u1", "mode": "update"})
    assert out["accepted"] is True
    assert lifecycle.is_draining() is True
    lifecycle.resume()
    assert lifecycle.is_draining() is False


def test_proxy_inflight_blocks(tmp_path: Path) -> None:
    lifecycle.mark_startup_ready()
    lifecycle.resume()
    db = tmp_path / "fleet.db"
    store.connect(db).close()
    lifecycle.proxy_enter()
    try:
        payload = lifecycle.stop_readiness_payload(db, tmp_path)
        assert payload["stop_allowed"] is False
        kinds = {b["kind"] for b in payload["blockers"]}
        assert "app_gateway_proxy" in kinds
    finally:
        lifecycle.proxy_exit()
