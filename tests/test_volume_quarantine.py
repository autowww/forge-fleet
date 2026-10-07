"""Tests for orphan volume quarantine registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fleet_server import environments, volume_quarantine


def test_env_volume_not_orphan(tmp_path: Path):
    data_dir = tmp_path / "fd"
    env_dir = environments.environments_dir(data_dir)
    rec = {
        "id": "forge_market_studio--prod",
        "volumes": {"pgdata": "forge_market_studio_pgdata", "appdata": "forge_market_studio_data"},
    }
    (env_dir / "forge_market_studio--prod.json").write_text(json.dumps(rec), encoding="utf-8")

    with patch("fleet_server.volume_quarantine.list_all_volume_names", return_value=["forge_market_studio_pgdata", "orphan_vol"]):
        with patch("fleet_server.volume_quarantine._mounted_volume_names", return_value=set()):
            with patch("fleet_server.volume_quarantine._volume_size_bytes", return_value=1024):
                orphans = volume_quarantine.discover_orphan_candidates(data_dir)
    names = {o["name"] for o in orphans}
    assert "forge_market_studio_pgdata" not in names
    assert "orphan_vol" in names


def test_registry_advances_candidate_to_quarantined(tmp_path: Path):
    data_dir = tmp_path / "fd2"
    data_dir.mkdir()
    with patch("fleet_server.volume_quarantine.discover_orphan_candidates", return_value=[{"name": "vol_a", "bytes": 500}]):
        out1 = volume_quarantine.refresh_registry(data_dir)
    assert out1["registry"]["volumes"]["vol_a"]["state"] == "candidate"
    with patch("fleet_server.volume_quarantine.discover_orphan_candidates", return_value=[{"name": "vol_a", "bytes": 500}]):
        out2 = volume_quarantine.refresh_registry(data_dir)
    assert out2["registry"]["volumes"]["vol_a"]["state"] == "quarantined"
