"""Guardian proxy paths and the apt package allowlist."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fleet_server import guardian_proxy, package_upgrade, route_registry


def test_guardian_routes_are_registered():
    assert route_registry.match_route("/v1/admin/guardian", "GET") is not None
    assert (
        route_registry.match_route("/v1/admin/guardian/findings/abc/decision", "POST")
        is not None
    )
    assert route_registry.match_route("/v1/remote-peers/mercury/admin/guardian", "GET") is not None


def test_upstream_paths():
    assert guardian_proxy.upstream_path("/v1/admin/guardian") == "/v1/guardian"
    assert (
        guardian_proxy.upstream_path("/v1/admin/guardian/findings/abc/decision")
        == "/v1/guardian/findings/abc/decision"
    )
    assert guardian_proxy.upstream_path("/v1/admin/space") is None


def test_package_override_fleet_guardian(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "apt_user")
    with patch.object(package_upgrade, "timer_active", return_value=True):
        out = package_upgrade.write_upgrade_signal(
            tmp_path, mode="upgrade", lifecycle_ok=True, package="fleet-guardian"
        )
    assert out["ok"] is True
    doc = json.loads((tmp_path / "upgrade-request.json").read_text(encoding="utf-8"))
    assert doc["package"] == "fleet-guardian"


def test_package_override_rejects_unknown(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "apt_user")
    out = package_upgrade.write_upgrade_signal(
        tmp_path, mode="upgrade", lifecycle_ok=True, package="bash"
    )
    assert out["ok"] is False
    assert out["error"] == "package_not_allowed"
