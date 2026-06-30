"""Install forge-cdp-manager FAEP package and exercise handlers."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet_server import fleet_apps

ZIP = Path(__file__).resolve().parents[1].parent / "forge-cdp-manager" / "dist" / "forge-cdp-manager-0.1.0.fleet-app.zip"


@pytest.mark.skipif(not ZIP.is_file(), reason="forge-cdp-manager fleet-app zip not built")
def test_cdp_manager_install_and_handlers(tmp_path: Path) -> None:
    data = ZIP.read_bytes()
    rec = fleet_apps.install_package_bytes(tmp_path, data)
    assert rec["id"] == "forge-cdp-manager"
    payload = fleet_apps.call_data_handler(tmp_path, "forge-cdp-manager", "leases")
    assert payload.get("ok", True)
    assert "rows" in payload
    action = fleet_apps.call_action_handler(tmp_path, "forge-cdp-manager", "release_stale", {"force": True})
    assert "cleaned" in action
