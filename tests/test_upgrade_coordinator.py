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


def _two_deps():
    from fleet_server.lifecycle_registry import LifecycleDependent

    return [
        LifecycleDependent(
            service_id="market-studio",
            prepare_url="http://127.0.0.1:19792/api/lifecycle/prepare-stop",
            readiness_url="http://127.0.0.1:19792/api/lifecycle/stop-readiness",
        ),
        LifecycleDependent(
            service_id="market-studio-dev",
            prepare_url="http://127.0.0.1:19793/api/lifecycle/prepare-stop/",
            readiness_url="http://127.0.0.1:19793/api/lifecycle/stop-readiness",
        ),
    ]


def test_resume_url_derives_from_prepare_url() -> None:
    a, b = _two_deps()
    assert a.resume_url == "http://127.0.0.1:19792/api/lifecycle/resume"
    assert b.resume_url == "http://127.0.0.1:19793/api/lifecycle/resume"


def test_fail_and_finish_resume_every_dependent() -> None:
    """Regression: aborted/finished upgrades left studios `draining: true`."""
    lifecycle.mark_startup_ready()
    calls: list[tuple[str, str]] = []

    def fake_http(method, url, body=None, timeout_s=5.0):
        calls.append((method, url))
        return 200, {"ok": True}

    with patch("fleet_server.upgrade_coordinator.list_dependents", return_value=_two_deps()):
        with patch("fleet_server.upgrade_coordinator._http_json", side_effect=fake_http):
            upgrade_coordinator.begin_upgrade({"mode": "upgrade", "upgrade_id": "u-resume"})
            upgrade_coordinator._prepare_all("u-resume", {"mode": "upgrade"})
            upgrade_coordinator.fail_upgrade("upgrade_blocked")
            resumed_after_fail = [u for m, u in calls if m == "POST" and u.endswith("/resume")]
            calls.clear()
            upgrade_coordinator.finish_upgrade(upgrade_id="u-resume", scheduled_restart=True)
            resumed_after_finish = [u for m, u in calls if m == "POST" and u.endswith("/resume")]
    upgrade_coordinator.clear_status()
    assert sorted(resumed_after_fail) == [
        "http://127.0.0.1:19792/api/lifecycle/resume",
        "http://127.0.0.1:19793/api/lifecycle/resume",
    ]
    assert sorted(resumed_after_finish) == sorted(resumed_after_fail)
