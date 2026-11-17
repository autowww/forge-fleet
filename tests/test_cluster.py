"""Tests for cluster mesh aggregation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import cluster, remote_peers


def test_cluster_payload_includes_local_when_peer_fails(tmp_path: Path):
    cluster.reset_cluster_cache()
    peers_doc = {
        "peers": [
            {
                "id": "granite",
                "label": "Granite",
                "base_url": "https://example.invalid",
                "bearer_token": "tok",
            }
        ]
    }
    peers_file = tmp_path / "etc" / "remote-peers.json"
    peers_file.parent.mkdir(parents=True)
    peers_file.write_text(__import__("json").dumps(peers_doc), encoding="utf-8")

    def fake_list(_data_dir):
        return {"ok": True, "peers": [{"id": "granite", "label": "Granite"}]}

    def fake_get(_data_dir, pid):
        if pid == "granite":
            return peers_doc["peers"][0]
        return None

    def fake_proxy_get(_data_dir, peer_id, path, **kwargs):
        return 502, b'{"ok":false,"error":"upstream_unreachable"}', "application/json"

    with patch("fleet_server.cluster.remote_peers.list_peers", side_effect=fake_list):
        with patch("fleet_server.cluster.remote_peers.get_peer", side_effect=fake_get):
            with patch("fleet_server.cluster.remote_peers.proxy_get", side_effect=fake_proxy_get):
                with patch(
                    "fleet_server.cluster._local_node",
                    return_value={
                        "scope": "local",
                        "peer_id": None,
                        "label": "Local",
                        "ok": True,
                        "errors": [],
                    },
                ):
                    out = cluster.cluster_payload(tmp_path, use_cache=False)
    assert out["ok"] is True
    assert len(out["nodes"]) == 2
    assert out["nodes"][0]["scope"] == "local"
    assert out["nodes"][1]["scope"] == "peer"
    assert out["nodes"][1]["ok"] is False