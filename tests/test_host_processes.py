"""Tests for host process listing."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fleet_server import host_processes, store
from fleet_server.main import FleetHandler


def test_snapshot_respects_limit_and_sort() -> None:
    fake_rows = [
        {"pid": 1, "name": "a", "cmd": "a", "cpu_pct": 1.0, "mem_pct": 1.0, "rss_kb": 100},
        {"pid": 2, "name": "b", "cmd": "b", "cpu_pct": 9.0, "mem_pct": 2.0, "rss_kb": 200},
        {"pid": 3, "name": "c", "cmd": "c", "cpu_pct": 5.0, "mem_pct": 9.0, "rss_kb": 900},
    ]

    def fake_list() -> list[int]:
        return [1, 2, 3]

    def fake_stat(pid: int) -> tuple[str, int, int] | None:
        return ("p", pid, pid)

    with (
        patch.object(host_processes, "_list_pids", fake_list),
        patch.object(host_processes, "_read_stat", fake_stat),
        patch.object(host_processes, "_read_cmdline", lambda pid: f"cmd-{pid}"),
        patch.object(host_processes, "_read_rss_kb", lambda pid: pid * 100),
        patch.object(host_processes, "_total_mem_kb", return_value=10000),
        patch.object(host_processes, "_system_jiffies", return_value=1000),
        patch.object(host_processes, "_cpu_pct_for_pid", lambda pid, u, s, now, total: float(pid)),
        patch.object(host_processes.os, "path", wraps=host_processes.os.path) as mock_path,
    ):
        mock_path.isdir.return_value = True
        out = host_processes.snapshot(limit=2, sort="cpu")
    assert out["ok"] is True
    assert len(out["processes"]) == 2
    assert out["processes"][0]["pid"] == 3


def test_get_v1_host_processes_http(tmp_path: Path) -> None:
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
        url = f"http://127.0.0.1:{port}/v1/host/processes?limit=5"
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)

    assert body.get("ok") is True
    assert isinstance(body.get("processes"), list)
