"""Tests for Fleet cleanup inventory and admin cleanup API."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from fleet_server import cleanup
from tests.test_migrations_api import _start_fleet_httpd, _stop_fleet_httpd


def _mk_dump(path: Path, size: int = 1024, age_days: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    if age_days > 0:
        mtime = time.time() - age_days * 86400.0
        os.utime(path, (mtime, mtime))


def test_gc_rollout_backups_keeps_newest(tmp_path: Path) -> None:
    root = tmp_path / "backups" / "market-studio"
    for i in range(5):
        _mk_dump(root / f"2026010{i}T000000Z.dump", size=100 + i, age_days=30.0 if i >= 2 else 0.0)
    out = cleanup.gc_rollout_backups(
        root.parent, keep_count=2, keep_days=14, service_ids=["market-studio"], dry_run=False
    )
    assert out["bytes_freed"] > 0
    assert len(out["purged"]) == 3
    assert len(list(root.glob("*.dump"))) == 2


def test_gc_rollout_backups_dry_run_leaves_files(tmp_path: Path) -> None:
    root = tmp_path / "backups" / "svc"
    for i in range(4):
        _mk_dump(root / f"2026010{i}T000000Z.dump", age_days=30.0 if i >= 1 else 0.0)
    out = cleanup.gc_rollout_backups(root.parent, keep_count=1, keep_days=14, service_ids=["svc"], dry_run=True)
    assert len(out["purged"]) == 3
    assert len(list(root.glob("*.dump"))) == 4


def test_gc_rollout_backups_keep_count_minimum_one(tmp_path: Path) -> None:
    root = tmp_path / "backups" / "svc"
    _mk_dump(root / "only.dump")
    out = cleanup.gc_rollout_backups(root.parent, keep_count=1, keep_days=1, service_ids=["svc"], dry_run=False)
    assert len(list(root.glob("*.dump"))) == 1
    assert not out["purged"]


def test_reject_disallowed_target_keys() -> None:
    out = cleanup.run_cleanup(Path("/tmp"), Path("/tmp/fleet.sqlite"), {"targets": {"volumes": {}}})
    assert out["ok"] is False
    assert "cleanup_target_not_allowed" in str(out.get("error"))


def test_operational_integrity_detects_missing_container() -> None:
    before = {
        "protected_containers": [{"name": "forge-market-app", "status": "Up 1 hour", "image": "x", "id": "a"}],
        "running_image_ids": ["sha1"],
    }
    after = {
        "protected_containers": [],
        "running_image_ids": [],
    }
    chk = cleanup.operational_integrity_check(before, after)
    assert chk["ok"] is False
    assert "forge-market-app" in chk["missing_containers"]


def test_cleanup_inventory_endpoint(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_inv"
    data_dir.mkdir()
    backup = data_dir / "backups" / "market-studio"
    _mk_dump(backup / "20260101T000000Z.dump", size=2048)
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(f"{base}/v1/admin/cleanup-inventory", method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
        assert out["ok"] is True
        assert out["rollout_backups"]["total_files"] == 1
        assert out["rollout_backups"]["total_bytes"] == 2048
    finally:
        _stop_fleet_httpd(httpd, th)


def test_admin_cleanup_dry_run_endpoint(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_cleanup"
    data_dir.mkdir()
    backup = data_dir / "backups" / "market-studio"
    for i in range(4):
        _mk_dump(backup / f"2026010{i}T000000Z.dump", size=512, age_days=30.0 if i >= 2 else 0.0)
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/admin/cleanup",
            data=json.dumps(
                {
                    "dry_run": True,
                    "targets": {"rollout_backups": {"keep_count": 2, "service_ids": ["market-studio"]}},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode())
        assert out["dry_run"] is True
        assert out["operational_integrity_ok"] is True
        assert len(list(backup.glob("*.dump"))) == 4
        assert len(out["results"]["rollout_backups"]["purged"]) == 2
    finally:
        _stop_fleet_httpd(httpd, th)


def test_admin_cleanup_rejects_volumes(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_reject"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/admin/cleanup",
            data=json.dumps({"targets": {"volumes": {}}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=30)
        assert exc.value.code == 400
        body = json.loads(exc.value.read().decode())
        assert "cleanup_target_not_allowed" in str(body.get("error"))
    finally:
        _stop_fleet_httpd(httpd, th)


def test_docker_images_safe_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from fleet_server import docker_gc

    out = docker_gc.prune_docker_images_safe(hours=0)
    assert out.get("skipped") is True
