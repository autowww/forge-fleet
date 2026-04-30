"""Ephemeral HTTP server: GET /v1/health host metrics shape."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fleet_server import store
from fleet_server.main import FleetHandler


def test_get_v1_health_host_metrics_shape(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleetdata"
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
        url = f"http://127.0.0.1:{port}/v1/health"
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)

    assert body.get("ok") is True
    host = body.get("host")
    assert isinstance(host, dict)
    cpu = host.get("cpu_usage_pct")
    assert cpu is None or isinstance(cpu, (int, float))
    mem = host.get("memory_used_pct")
    assert mem is None or isinstance(mem, (int, float))
    la = host.get("loadavg_1m")
    assert la is None or isinstance(la, (int, float))


def test_get_v1_health_requires_auth_when_not_loopback_skip(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleetdata2"
    data_dir.mkdir()
    db = data_dir / "fleet.sqlite"
    store.connect(db).close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = "need-this"
    httpd.loopback_bind_skips_auth = False
    httpd.fleet_started_epoch = time.time()
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        url = f"http://127.0.0.1:{port}/v1/health"
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(url, timeout=30)
        assert ei.value.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)
