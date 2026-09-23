"""Tests for GET /v1/capacity headroom math and mesh aggregate."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet_server import capacity, remote_peers, store
from fleet_server.main import FleetHandler


def _nvidia_host() -> dict:
    return {
        "cpus": 16,
        "cpu_cores_physical": 8,
        "cpu_usage_pct": 50.0,
        "memory": {"total_kb": 64 * 1024 * 1024, "available_kb": 32 * 1024 * 1024, "used_pct": 50.0},
        "gpu": {
            "nvidia": {
                "available": True,
                "devices": [
                    {
                        "index": 0,
                        "name": "RTX",
                        "utilization_pct": 10,
                        "memory_used_mib": 4000,
                        "memory_total_mib": 24000,
                    }
                ],
            }
        },
    }


def test_from_host_snapshot_nvidia_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_GPU_RESERVED", json.dumps([{"index": 0, "vram_mb": 4096, "label": "ollama"}]))
    out = capacity.from_host_snapshot(_nvidia_host())
    assert out["cpu"]["available_cores"] == 8.0
    assert out["memory"]["total_mb"] == 65536
    assert out["memory"]["available_mb"] == 32768
    assert len(out["gpu"]) == 1
    g0 = out["gpu"][0]
    assert g0["vram_total_mb"] == 24000
    assert g0["vram_reserved_mb"] == 4096
    assert g0["vram_available_mb"] == 24000 - 4000 - 4096
    assert out["reservations"] == []


def test_from_host_snapshot_amd_no_vram() -> None:
    host = {
        "cpus": 4,
        "cpu_usage_pct": None,
        "memory": {},
        "gpu": {"amdgpu_sysfs": {"available": True, "devices": [{"index": 0, "utilization_pct": 5.0}]}},
    }
    out = capacity.from_host_snapshot(host)
    assert out["gpu"][0]["vendor"] == "amd"
    assert out["gpu"][0]["vram_available_mb"] is None
    assert out["gpu"][0]["note"]


def test_get_v1_capacity_http(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    data_dir.mkdir()
    db = data_dir / "fleet.sqlite"
    store.connect(db).close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = ""
    httpd.loopback_bind_skips_auth = True
    httpd.fleet_started_epoch = time.time()
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        with patch("fleet_server.capacity.host_stats.snapshot", return_value=_nvidia_host()):
            url = f"http://127.0.0.1:{port}/v1/capacity"
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)

    assert body.get("ok") is True
    assert body["capacity"]["cpu"]["cores_logical"] == 16


def test_mesh_capacity_peer_unreachable(tmp_path: Path) -> None:
    capacity.reset_mesh_capacity_cache()
    data_dir = tmp_path / "fleet"
    remote_peers.upsert_peer(
        data_dir,
        "down",
        label="Down",
        base_url="https://missing.example",
        bearer_token="tok",
    )
    with patch("fleet_server.capacity.host_stats.snapshot", return_value=_nvidia_host()):
        with patch(
            "fleet_server.remote_peers.proxy_get",
            return_value=(502, b'{"ok":false,"error":"upstream_unreachable"}', "application/json"),
        ):
            out = capacity.mesh_capacity(data_dir, cache_ttl_s=0)
    assert out["ok"] is True
    assert len(out["nodes"]) == 2
    assert out["nodes"][0]["scope"] == "local"
    assert out["nodes"][1]["ok"] is False
