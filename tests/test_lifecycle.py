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


def test_stale_queued_jobs_do_not_block_stop(tmp_path: Path, monkeypatch) -> None:
    """Regression (Granite 2026-10-07): 50 workspace jobs queued since May with
    `pending_upload` vetoed every cooperative Fleet upgrade (`upgrade_blocked`)."""
    import time

    lifecycle.mark_startup_ready()
    lifecycle.resume()
    db = tmp_path / "fleet.db"
    conn = store.connect(db)
    fresh = store.insert_job(conn, kind="docker_argv", argv=["true"], session_id="s", meta={})
    stale = store.insert_job(conn, kind="docker_argv", argv=["true"], session_id="s", meta={})
    running = store.insert_job(conn, kind="docker_argv", argv=["true"], session_id="s", meta={})
    old = time.time() - 30 * 86400
    conn.execute("UPDATE jobs SET created = ?, updated = ? WHERE id = ?", (old, old, stale))
    conn.execute("UPDATE jobs SET status = 'running', created = ?, updated = ? WHERE id = ?", (old, old, running))
    conn.commit()
    conn.close()

    payload = lifecycle.stop_readiness_payload(db, tmp_path)
    ids = {b["id"]: b["detail"] for b in payload["blockers"] if b["kind"] == "fleet_job"}
    assert payload["stop_allowed"] is False
    assert ids[fresh] == "queued", "a just-queued job is imminent work"
    assert ids[running] == "running", "running jobs always block, whatever their age"
    assert stale not in ids, "a job queued for 30 days is abandoned, not imminent"

    monkeypatch.setenv("FLEET_LIFECYCLE_QUEUED_BLOCK_MAX_AGE_SEC", "0")
    payload = lifecycle.stop_readiness_payload(db, tmp_path)
    ids = {b["id"] for b in payload["blockers"] if b["kind"] == "fleet_job"}
    assert ids == {running}, "max-age 0 means queued jobs never block"
