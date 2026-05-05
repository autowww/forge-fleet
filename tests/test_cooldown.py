"""Cooldown events table and aggregation API helpers."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from fleet_server import store, versioning
from fleet_server.main import FleetHandler


def test_cooldown_table_and_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "c.sqlite"
    conn = store.connect(db)
    try:
        row = store.get_fleet_version_row(conn)
        assert int(row["db_schema_version"]) == int(versioning.FLEET_DB_SCHEMA_VERSION)
        t0, t1, n = store.cooldown_time_bounds(conn)
        assert t0 is None and t1 is None and n == 0
    finally:
        conn.close()


def test_insert_aggregate_and_presets(tmp_path: Path) -> None:
    db = tmp_path / "w.sqlite"
    now = time.time()
    conn = store.connect(db)
    try:
        store.insert_cooldown_event(conn, duration_s=1.5, ts=now - 3600, kind="thermal_llm_guard")
        store.insert_cooldown_event(conn, duration_s=2.5, ts=now - 10, kind="thermal_llm_guard")
        tot, cnt = store.cooldown_aggregate_s(conn, t0=now - 7200, t1=now + 1)
        assert cnt == 2
        assert abs(tot - 4.0) < 1e-6
        presets = store.cooldown_summary_presets(conn)
        assert "today" in presets
        assert "since_first" in presets
        assert presets["since_first"]["event_count"] == 2
        assert presets["since_first"]["total_cooldown_s"] >= 4.0 - 1e-5
    finally:
        conn.close()


def test_cooldown_summary_payload_period(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    conn = store.connect(db)
    try:
        p = store.cooldown_summary_payload(conn, period="today")
        assert p.get("ok") is True
        assert "total_cooldown_s" in p
        assert "event_count" in p
    finally:
        conn.close()


def test_post_cooldown_events_clamps_and_response_shape(tmp_path: Path) -> None:
    data_dir = tmp_path / "clamp"
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
        url = f"http://127.0.0.1:{port}/v1/cooldown-events"
        payload = json.dumps({"duration_s": 200_000.0, "kind": "thermal_llm_guard"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        assert resp.getcode() == 201
        assert out.get("ok") is True
        assert out.get("clamped") is True
        assert abs(float(out.get("accepted_duration_s", 0)) - 86400.0) < 0.01
        assert isinstance(out.get("id"), int)
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)

    conn = store.connect(db)
    try:
        tot, cnt = store.cooldown_aggregate_s(conn, t0=0, t1=time.time() + 10)
        assert cnt == 1
        assert abs(tot - 86400.0) < 0.01
    finally:
        conn.close()
