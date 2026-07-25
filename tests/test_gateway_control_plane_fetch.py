"""Tests for forge-gateway control plane scrape helper."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fleet_server import forge_llm_service as fls


def test_fetch_gateway_control_plane_json() -> None:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"rollup": {"requests": 3}, "active": {"active_model": "qwen3:30b-a3b"}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_a: object) -> None:
            return None

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        out = fls.fetch_gateway_control_plane(port)
        assert out is not None
        assert out["rollup"]["requests"] == 3
    finally:
        srv.shutdown()
