"""Tests for Space Guardian policy and scheduler."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet_server import space_guardian, space_policy
from tests.test_migrations_api import _start_fleet_httpd, _stop_fleet_httpd


def test_tier0_targets_include_rollout_backups():
    targets = space_policy.tier0_cleanup_targets()
    assert "rollout_backups" in targets
    assert targets["rollout_backups"].get("strict_keep_count") is True


def test_detect_pressure_low_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    monkeypatch.setattr(
        "fleet_server.host_stats.disk_space_snapshot",
        lambda: [{"mount": "/", "total_gb": 100, "used_gb": 90, "free_gb": 10, "used_pct": 90.0}],
    )
    out = space_guardian.detect_pressure(data_dir)
    assert out["under_pressure"] is True


def test_run_skipped_when_upgrade_active(tmp_path: Path):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    db_path = data_dir / "fleet.sqlite"
    with patch("fleet_server.space_guardian.upgrade_active", return_value=True):
        out = space_guardian.run_tier(data_dir, db_path, 0, dry_run=False, trigger="scheduled")
    assert out.get("skipped") is True
    assert out.get("reason") == "upgrade_active"


def test_space_endpoint(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_api"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(f"{base}/v1/admin/space", method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
        assert out["ok"] is True
        assert "pressure" in out
        assert "tier0_targets" in out
    finally:
        _stop_fleet_httpd(httpd, th)


def test_snapshot_space_summary_never_calls_app_gc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Snapshot is polled every ~20s; it must not fan out to market-app GC inventory."""
    from fleet_server import cleanup as fleet_cleanup

    data_dir = tmp_path / "fd_meta"
    data_dir.mkdir()
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("app_gc")
        raise AssertionError("snapshot summary reached fetch_app_gc_per_env")

    monkeypatch.setattr(fleet_cleanup, "fetch_app_gc_per_env", _boom)
    out = space_guardian.space_meta_summary(data_dir, data_dir / "fleet.sqlite")
    assert calls == []
    assert "guardian_enabled" in out

    full = space_guardian.space_status(data_dir, data_dir / "fleet.sqlite", include_app_gc=False)
    assert full["app_gc_per_env"]["skipped"] is True


def test_app_gc_inventory_is_cached_per_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fleet_server import cleanup as fleet_cleanup

    data_dir = tmp_path / "fd_cache"
    data_dir.mkdir()
    fleet_cleanup._APP_GC_CACHE.clear()
    monkeypatch.setattr(
        fleet_cleanup.app_gateway,
        "load_gateway",
        lambda _d, sid: {"upstream": f"http://127.0.0.1:1/{sid}"},
    )
    opened: list[str] = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return b'{"ok": true, "reclaimable_bytes": 7}'

    def _urlopen(req, timeout):
        opened.append(req.full_url)
        assert timeout <= 15.0
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", _urlopen)
    first = fleet_cleanup.fetch_app_gc_per_env(data_dir, service_ids=["market-studio"])
    second = fleet_cleanup.fetch_app_gc_per_env(data_dir, service_ids=["market-studio"])
    assert len(opened) == 1
    assert first["environments"]["market-studio"]["reclaimable_bytes"] == 7
    assert second["environments"]["market-studio"]["cached"] is True

    monkeypatch.setenv("FLEET_APP_GC_CACHE_TTL_SEC", "0")
    fleet_cleanup.fetch_app_gc_per_env(data_dir, service_ids=["market-studio"])
    assert len(opened) == 2
    fleet_cleanup._APP_GC_CACHE.clear()


def test_tier1_skipped_without_pressure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "fd_t1"
    data_dir.mkdir()
    db_path = data_dir / "fleet.sqlite"
    monkeypatch.setattr(
        "fleet_server.space_guardian.detect_pressure",
        lambda _d: {"ok": True, "under_pressure": False},
    )
    out = space_guardian.run_tier(data_dir, db_path, 1, dry_run=True, trigger="scheduled")
    assert out.get("skipped") is True
    assert out.get("reason") == "no_pressure"


def test_startup_gc_runs_tier0(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "fd_gc"
    data_dir.mkdir()
    db_path = data_dir / "fleet.sqlite"
    calls: list[int] = []

    def fake_run_tier(data_dir, db_path, tier, *, dry_run=False, trigger="manual"):
        calls.append(tier)
        return {"ok": True, "tier": tier, "bytes_freed_total": 0, "operational_integrity_ok": True}

    monkeypatch.setattr(space_guardian, "run_tier", fake_run_tier)
    space_guardian.run_startup_gc(data_dir, db_path)
    assert calls == [0]
