"""Admin packaged static: app-src fragments for parts 2–6."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

from fleet_server.main import FleetHandler

_SAMPLE = {
    "part2": "tile-marks.js",
    "part3": "telemetry-x-axis.js",
    "part4": "chart-y-hint.js",
    "part5": "auth-errors.js",
    "part6": "snapshot-load.js",
}


def test_admin_static_serves_app_bundle() -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        with urlopen(f"{base}/admin/static/app-bundle.js", timeout=5) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
        assert body.lstrip().startswith("(function ()")
        assert body.rstrip().endswith("})();")
        assert "loadSnapshot" in body
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


def test_admin_static_serves_app_src_parts_2_through_6() -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        for part, filename in _SAMPLE.items():
            path = f"/admin/static/app-src/{part}/{filename}"
            with urlopen(f"{base}{path}", timeout=5) as resp:
                assert resp.status == 200
                body = resp.read()
            assert len(body) > 10
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
