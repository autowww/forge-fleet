"""Tests for app deployment status endpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import app_deployments


def test_get_app_deployment_not_found(tmp_path: Path):
    out = app_deployments.get_app_deployment(tmp_path, "missing")
    assert out["ok"] is False
    assert out["error"] == "not_found"


def test_get_app_deployment_with_compose(tmp_path: Path):
    from fleet_server import container_layout
    import json

    container_layout.ensure_layout(tmp_path)
    root = tmp_path / "stack"
    root.mkdir()
    (root / "compose.yaml").write_text("services:\n  market-app:\n    image: forge-market-app:abc\n", encoding="utf-8")
    rec = {
        "version": 1,
        "id": "market-studio-dev",
        "type_id": "forge_market_studio",
        "label": "market-studio-dev",
        "compose_root": str(root),
        "compose_files": [],
    }
    p = container_layout.service_file(tmp_path, "market-studio-dev")
    p.write_text(json.dumps(rec), encoding="utf-8")
    with patch("fleet_server.app_deployments.mcs.compose_ps") as mock_ps:
        mock_ps.return_value = (
            [{"Service": "market-app", "Image": "forge-market-app:abc123", "State": "running", "ID": "cid1"}],
            None,
        )
        with patch("fleet_server.app_deployments._inspect_container_image") as mock_inspect:
            mock_inspect.return_value = {"digest": "sha256:abc123", "tag": "abc123"}
            with patch("fleet_server.app_deployments.mcs.status_for_record") as mock_status:
                mock_status.return_value = {"ok": True, "services_running": 1}
                out = app_deployments.get_app_deployment(tmp_path, "market-studio-dev")
    assert out["ok"] is True
    assert out["digest"] == "sha256:abc123"
    assert out["tag"] == "abc123"
    assert out["compose_project"] == "market-studio-dev"
