"""Tests for cluster mesh aggregation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import cluster, ecosystem


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
    assert out["schema_version"] == "forge.fleet.cluster.v1"
    assert len(out["nodes"]) == 2
    assert out["nodes"][0]["scope"] == "local"
    assert out["nodes"][1]["scope"] == "peer"
    assert out["nodes"][1]["ok"] is False


def test_ecosystem_places_known_services():
    nodes = [
        {
            "label": "Granite",
            "node_id": "granite",
            "scope": "peer",
            "peer_id": "granite",
            "ok": True,
            "services": [
                {
                    "id": "default",
                    "type_id": "forge_llm",
                    "status": {"ps_ok": True, "services_running": 2, "services_total": 2},
                },
                {
                    "id": "open-webui",
                    "type_id": "compose",
                    "status": {"ps_ok": True, "services_running": 1, "services_total": 1},
                },
            ],
        }
    ]
    view = ecosystem.ecosystem_view(nodes)
    by_id = {c["id"]: c for c in view["components"]}
    assert by_id["forge-llm"]["status"] == "running"
    assert by_id["forge-llm"]["placements"][0]["node_label"] == "Granite"
    assert by_id["open-webui"]["connects_to"][0]["id"] == "forge-llm"
    assert by_id["market-studio"]["status"] == "absent"
    assert by_id["fleet"]["placements"][0]["state"] == "up"