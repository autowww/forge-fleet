"""Tests for operator UI settings and setup recipes."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fleet_server import operator_ui_settings, store
from fleet_server.main import FleetHandler


def test_put_get_settings_and_recipes(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    out = operator_ui_settings.put_settings(
        data_dir,
        {
            "machine_role": "server",
            "connection": {
                "peer_id": "worker",
                "peer_label": "Worker",
                "remote_base_url": "https://fleet.example",
            },
            "edge": {"public_hostname": "fleet.example", "caddy_port": 18767},
        },
    )
    assert out["ok"] is True
    assert out["settings"]["machine_role"] == "server"
    assert out["settings"]["connection"]["peer_id"] == "worker"
    loaded = operator_ui_settings.get_settings(data_dir)
    assert loaded["settings"]["edge"]["public_hostname"] == "fleet.example"
    ids = [r["id"] for r in loaded["recipes"]]
    assert "ui_connection" in ids
    assert "root_cloudflared" in ids
    assert "user_laptop" not in ids
    edge_ids = [r["id"] for r in loaded.get("edge_recipes", [])]
    assert "edge_cloudflare" in edge_ids
    assert "edge_caddy" in edge_ids


def test_setup_completed_defaults_false(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    loaded = operator_ui_settings.get_settings(data_dir)
    assert loaded["settings"]["setup_completed"] is False
    out = operator_ui_settings.put_settings(data_dir, {"setup_completed": True})
    assert out["settings"]["setup_completed"] is True


def test_get_ui_settings_without_bearer(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    db = data_dir / "fleet.sqlite"
    store.connect(db).close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = "secret-token"
    httpd.loopback_bind_skips_auth = False
    httpd.fleet_started_epoch = time.time()
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        url = f"http://127.0.0.1:{port}/v1/operator/ui-settings"
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)

    assert body.get("ok") is True
    assert body["settings"]["setup_completed"] is False


def test_laptop_recipes_exclude_root(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    operator_ui_settings.put_settings(data_dir, {"machine_role": "laptop"})
    loaded = operator_ui_settings.get_settings(data_dir)
    ids = [r["id"] for r in loaded["recipes"]]
    assert "user_laptop" in ids
    assert "root_cloudflared" not in ids
    assert loaded.get("edge_recipes") == []
