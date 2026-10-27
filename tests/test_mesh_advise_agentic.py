"""Agentic-dev placement advice: local first, peers by free capacity, no transfer term."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from fleet_server import mesh_advise, store


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    return db


def test_local_preferred_when_free(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with mock.patch.dict(os.environ, {"FLEET_AGENTIC_DEV_NODE": "1", "FLEET_AGENTIC_DEV_MAX_RUNNING": "2"}):
        out = mesh_advise.advise_agentic_dev(tmp_path, db)
    assert out["ok"] is True and out["workload"] == "agentic_dev"
    assert out["best"]["node_id"] == "local"
    assert out["best"]["free"] == 2


def test_peer_used_when_local_not_agentic(tmp_path: Path) -> None:
    db = _db(tmp_path)
    peers = {"peers": [{"id": "granite"}, {"id": "idle-box"}]}
    caps = {
        "granite": {"http": 200, "agentic_dev": True, "free": 1, "max_running": 2},
        "idle-box": {"http": 200, "agentic_dev": False, "free": 4, "max_running": 4},
    }
    with mock.patch.dict(os.environ, {"FLEET_AGENTIC_DEV_NODE": "", "FLEET_AGENTIC_GIT_TOKEN": "", "FLEET_AGENTIC_DEV_RUNNER": "docker"}), \
            mock.patch("fleet_server.remote_peers.list_peers", return_value=peers), \
            mock.patch("fleet_server.agentic_dev_job.peer_capacity", side_effect=lambda _d, pid: caps[pid]):
        out = mesh_advise.advise_agentic_dev(tmp_path, db)
    assert out["best"]["node_id"] == "granite"
    assert [c["node_id"] for c in out["ranked"]] == ["granite"]


def test_no_eligible_node(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with mock.patch.dict(os.environ, {"FLEET_AGENTIC_DEV_NODE": "", "FLEET_AGENTIC_GIT_TOKEN": "", "FLEET_AGENTIC_DEV_RUNNER": "docker"}), \
            mock.patch("fleet_server.remote_peers.list_peers", return_value={"peers": []}):
        out = mesh_advise.advise_agentic_dev(tmp_path, db)
    assert out["best"] is None
    assert out["candidates"][0]["agentic_dev"] is False
