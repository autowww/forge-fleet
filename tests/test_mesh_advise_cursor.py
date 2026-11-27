"""Cursor ecosystem placement follows the host that has cursor-agent."""

from __future__ import annotations

import json
from unittest import mock

from fleet_server import mesh_advise


def test_peer_with_binary_beats_local_without_one(tmp_path) -> None:
    peers = {"peers": [{"id": "mercury"}, {"id": "idle-box"}]}

    def proxy(_data, pid, _path):
        if pid == "mercury":
            body = json.dumps({"ok": True, "host_binary": "/home/leo/.local/bin/cursor-agent"}).encode()
            return 200, body, "application/json"
        return 200, json.dumps({"ok": False, "host_binary": ""}).encode(), "application/json"

    with mock.patch("fleet_server.cursor_cli_job.configured_binary", return_value=None), \
            mock.patch("fleet_server.remote_peers.list_peers", return_value=peers), \
            mock.patch("fleet_server.remote_peers.proxy_get", side_effect=proxy):
        out = mesh_advise.advise_cursor_ecosystem(tmp_path)
    assert out["workload"] == "cursor_ecosystem"
    assert out["best"]["node_id"] == "mercury"
    assert [row["node_id"] for row in out["ranked"]] == ["mercury"]


def test_no_cursor_host(tmp_path) -> None:
    with mock.patch("fleet_server.cursor_cli_job.configured_binary", return_value=None), \
            mock.patch("fleet_server.remote_peers.list_peers", return_value={"peers": []}):
        out = mesh_advise.advise_cursor_ecosystem(tmp_path)
    assert out["best"] is None
    assert out["candidates"][0]["cursor_agent"] is False
