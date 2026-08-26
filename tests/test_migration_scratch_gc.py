"""Tests for migration bundle scratch GC and cancel purge."""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest

from fleet_server import migrations as mig
from fleet_server import store
from tests.test_migrations_api import _start_fleet_httpd, _stop_fleet_httpd


def _bundle_dir(data_dir: Path, mid: str) -> Path:
    root = data_dir / "migration-bundles" / mid
    root.mkdir(parents=True, exist_ok=True)
    (root / "extracted").mkdir(parents=True, exist_ok=True)
    (root / "extracted" / "data.bin").write_bytes(b"x" * 1024)
    return root


def test_cancel_migration_deletes_bundle_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_cancel"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        mid = created["id"]
        bundle = _bundle_dir(data_dir, mid)
        assert bundle.is_dir()

        cancel_req = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(cancel_req, timeout=30) as resp_cancel:
            out = json.loads(resp_cancel.read().decode())
        assert out["ok"] is True
        assert out.get("bytes_freed", 0) > 0
        assert not bundle.exists()
    finally:
        _stop_fleet_httpd(httpd, th)


def test_gc_purges_terminal_failed_migration(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_gc"
    db = data_dir / "fleet.sqlite"
    data_dir.mkdir()
    conn = store.connect(db)
    try:
        mid = store.create_migration(
            conn,
            source_label="a",
            target_label="b",
            step_kinds=["seed_corpus_volume", "migrate_db", "deploy_service"],
        )
        store.update_migration(conn, mid, status="failed", bundle_state="ready")
        for step in store.list_migration_steps(conn, mid):
            if step["kind"] in {"seed_corpus_volume", "migrate_db"}:
                store.update_step(conn, str(step["id"]), status="completed")
        _bundle_dir(data_dir, mid)
        out = mig.gc_stale_migration_scratch(data_dir, db)
        assert out["bytes_freed"] > 0
        assert any(p["id"] == mid for p in out["purged"])
        assert not (data_dir / "migration-bundles" / mid).exists()
    finally:
        conn.close()


def test_gc_keeps_uploading_bundle(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_up"
    db = data_dir / "fleet.sqlite"
    data_dir.mkdir()
    conn = store.connect(db)
    try:
        mid = store.create_migration(conn, step_kinds=["seed_corpus_volume"])
        store.update_migration(conn, mid, bundle_state="uploading")
        _bundle_dir(data_dir, mid)
        out = mig.gc_stale_migration_scratch(data_dir, db)
        assert not any(p["id"] == mid for p in out["purged"])
        assert (data_dir / "migration-bundles" / mid).is_dir()
    finally:
        conn.close()


def test_gc_purges_failed_extract_after_retention(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_ret"
    db = data_dir / "fleet.sqlite"
    data_dir.mkdir()
    conn = store.connect(db)
    try:
        mid = store.create_migration(
            conn,
            step_kinds=["seed_corpus_volume", "migrate_db"],
        )
        store.update_migration(conn, mid, status="active", bundle_state="ready")
        steps = store.list_migration_steps(conn, mid)
        for step in steps:
            if step["kind"] == "seed_corpus_volume":
                store.update_step(conn, str(step["id"]), status="completed")
            if step["kind"] == "migrate_db":
                store.update_step(conn, str(step["id"]), status="failed")
                conn.execute(
                    "UPDATE migration_steps SET updated = ? WHERE id = ?",
                    (time.time() - 25 * 3600, str(step["id"])),
                )
                conn.commit()
        _bundle_dir(data_dir, mid)
        out = mig.gc_stale_migration_scratch(data_dir, db, retention_hours=24.0)
        assert any(p["id"] == mid for p in out["purged"])
    finally:
        conn.close()


def test_gc_dry_run_does_not_delete(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_dry"
    db = data_dir / "fleet.sqlite"
    data_dir.mkdir()
    conn = store.connect(db)
    try:
        mid = store.create_migration(conn, step_kinds=["seed_corpus_volume"])
        store.update_migration(conn, mid, status="cancelled", bundle_state="ready")
        store.update_step(conn, str(store.list_migration_steps(conn, mid)[0]["id"]), status="skipped")
        _bundle_dir(data_dir, mid)
        out = mig.gc_stale_migration_scratch(data_dir, db, dry_run=True)
        assert out["dry_run"] is True
        assert out["bytes_freed"] > 0
        assert (data_dir / "migration-bundles" / mid).is_dir()
    finally:
        conn.close()


def test_admin_migration_scratch_gc_endpoint(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_admin"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        db = data_dir / "fleet.sqlite"
        conn = store.connect(db)
        try:
            mid = store.create_migration(conn, step_kinds=["seed_corpus_volume"])
            store.update_migration(conn, mid, status="completed", bundle_state="ready")
            store.update_step(conn, str(store.list_migration_steps(conn, mid)[0]["id"]), status="completed")
        finally:
            conn.close()
        _bundle_dir(data_dir, mid)

        dry_req = urllib.request.Request(
            f"{base}/v1/admin/migration-scratch-gc",
            data=json.dumps({"dry_run": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(dry_req, timeout=30) as resp:
            dry = json.loads(resp.read().decode())
        assert dry["dry_run"] is True
        assert (data_dir / "migration-bundles" / mid).is_dir()

        run_req = urllib.request.Request(
            f"{base}/v1/admin/migration-scratch-gc",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(run_req, timeout=30) as resp2:
            ran = json.loads(resp2.read().decode())
        assert ran["dry_run"] is False
        assert not (data_dir / "migration-bundles" / mid).exists()
    finally:
        _stop_fleet_httpd(httpd, th)


def test_docker_gc_skips_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from fleet_server import docker_gc

    monkeypatch.setenv("FLEET_DOCKER_BUILDER_PRUNE_HOURS", "0")
    out = docker_gc.prune_docker_builder_cache()
    assert out.get("skipped") is True
