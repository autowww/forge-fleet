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


def test_fetch_gateway_catalog_json() -> None:
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"schema": "forge-llm-catalog-v1", "artifact_pins": []}).encode()
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
        out = fls.fetch_gateway_catalog(port)
        assert out is not None
        assert out["schema"] == "forge-llm-catalog-v1"
    finally:
        srv.shutdown()


def test_gateway_bearer_resolution_order(tmp_path, monkeypatch) -> None:
    for key in fls._GATEWAY_BEARER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setattr(fls.Path, "home", classmethod(lambda cls: tmp_path))
    compose_root = tmp_path / "svc"
    compose_root.mkdir()

    assert fls._gateway_scrape_bearer(compose_root) == ""

    # Granite layout: gateway token only in the service compose .env (written by rollout).
    (compose_root / ".env").write_text("GATEWAY_AUTH_REQUIRED=true\nFORGE_API_TOKEN=compose-tok\n")
    assert fls._gateway_scrape_bearer(compose_root) == "compose-tok"

    # Fleet user env (LLM_BEARER_TOKEN) wins over the compose .env.
    (cfg / "forge-fleet").mkdir(parents=True)
    (cfg / "forge-fleet" / "forge-fleet.env").write_text("FLEET_BEARER_TOKEN=fleet\nLLM_BEARER_TOKEN='fleet-llm'\n")
    assert fls._gateway_scrape_bearer(compose_root) == "fleet-llm"

    # Process env wins over files.
    monkeypatch.setenv("FORGE_API_TOKEN", "env-tok")
    assert fls._gateway_scrape_bearer(compose_root) == "env-tok"


def test_fetch_gateway_catalog_detailed_reports_401(monkeypatch, tmp_path) -> None:
    for key in fls._GATEWAY_BEARER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "nocfg"))
    monkeypatch.setattr(fls.Path, "home", classmethod(lambda cls: tmp_path))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"detail":"Unauthorized"}')

        def log_message(self, *_a: object) -> None:
            return None

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        data, err = fls.fetch_gateway_catalog_detailed(port)
        assert data is None
        assert err is not None and err.startswith("gateway_http_401")
        assert "no gateway bearer" in err
    finally:
        srv.shutdown()
