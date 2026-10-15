"""Tests for Memory Guardian planning and safety."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest.mock import patch

from fleet_server import capacity_policy, memory_guardian
from tests.test_migrations_api import _start_fleet_httpd, _stop_fleet_httpd


def test_plan_never_includes_pinned(tmp_path: Path):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    db_path = data_dir / "fleet.sqlite"
    capacity_policy.save_policy(
        data_dir,
        {
            "memory": {
                "pinned_service_ids": ["default"],
                "warm_service_ids": [],
            }
        },
    )
    with patch("fleet_server.container_layout.list_service_records", return_value=[]):
        plan = memory_guardian._plan_stops(data_dir)
    assert plan == []


def test_run_tier_dry_run_does_not_stop(tmp_path: Path):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    db_path = data_dir / "fleet.sqlite"
    with patch("fleet_server.memory_guardian._stop_compose_service") as stop_mock:
        out = memory_guardian.run_tier(data_dir, db_path, 1, dry_run=True, trigger="manual")
    stop_mock.assert_not_called()
    assert out.get("ok") is True
    assert out.get("dry_run") is True


def test_memory_endpoint(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_api"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(f"{base}/v1/admin/memory", method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
        assert out["ok"] is True
        assert "pressure" in out
        assert "plan" in out
    finally:
        _stop_fleet_httpd(httpd, th)


def test_run_skipped_when_upgrade_active(tmp_path: Path):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    db_path = data_dir / "fleet.sqlite"
    with patch("fleet_server.space_guardian.upgrade_active", return_value=True):
        out = memory_guardian.run_tier(data_dir, db_path, 0, dry_run=False, trigger="scheduled")
    assert out.get("skipped") is True
    assert out.get("reason") == "upgrade_active"


def test_snapshot_memory_summary_no_detail_fanout(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "fd_meta"
    data_dir.mkdir()
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("detail")
        raise AssertionError("snapshot should not call memory_status")

    monkeypatch.setattr(memory_guardian, "memory_status", _boom)
    out = memory_guardian.memory_meta_summary(data_dir, data_dir / "fleet.sqlite")
    assert calls == []
    assert "guardian_enabled" in out
