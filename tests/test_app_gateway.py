"""Tests for generic Fleet app gateway (loopback proxy, no new tunnel)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from fleet_server import app_gateway
from fleet_server import migration_jobs
from fleet_server.migrations import run_migration_step
from fleet_server import store


def test_loopback_upstream_required() -> None:
    with pytest.raises(ValueError, match="loopback"):
        app_gateway.validate_loopback_upstream("http://example.com:80")


def test_upsert_dotenv_generates_and_preserves(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=bar\nAPP_TOKEN=\n", encoding="utf-8")
    app_gateway.upsert_dotenv(env, "APP_TOKEN", "secret-1")
    text = env.read_text(encoding="utf-8")
    assert "FOO=bar" in text
    assert "APP_TOKEN=secret-1" in text
    assert app_gateway.read_dotenv_value(env, "APP_TOKEN") == "secret-1"


def test_prepare_compose_app_bearer_generates_once(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("APP_TOKEN=\n", encoding="utf-8")
    meta = {"compose_root": str(tmp_path), "app_bearer_env": "APP_TOKEN"}
    first = app_gateway.prepare_compose_app_bearer(meta)
    second = app_gateway.prepare_compose_app_bearer(meta)
    assert first["generated"] is True
    assert second["generated"] is False
    assert app_gateway.read_dotenv_value(env, "APP_TOKEN")


def test_register_from_meta_uses_fleet_path_not_tunnel(tmp_path) -> None:
    (tmp_path / ".env").write_text("", encoding="utf-8")
    data_dir = tmp_path / "fleet-data"
    rec = app_gateway.register_from_migration_meta(
        data_dir,
        {
            "gateway_service_id": "example-app",
            "gateway_upstream": "http://127.0.0.1:19792",
            "compose_root": str(tmp_path),
            "app_bearer_env": "APP_TOKEN",
        },
    )
    assert rec["path"] == "/v1/app-gateways/example-app"
    assert rec["new_tunnel"] is False
    assert rec["via"] == "fleet_api"
    assert rec["bearer_configured"] is True
    listed = app_gateway.list_gateways(data_dir)
    assert listed[0]["service_id"] == "example-app"
    assert "upstream_bearer" not in listed[0]


def test_register_rejects_new_tunnel_flag(tmp_path) -> None:
    with pytest.raises(ValueError, match="Cloudflare"):
        app_gateway.register_from_migration_meta(
            tmp_path / "d",
            {
                "gateway_service_id": "x",
                "gateway_upstream": "http://127.0.0.1:9",
                "prefer_fleet_gateway": False,
                "create_cloudflare_tunnel": True,
            },
        )


class _Upstream(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: ARG002
        return

    def do_GET(self) -> None:
        auth = self.headers.get("Authorization") or ""
        body = json.dumps({"ok": True, "auth": auth, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_proxy_injects_app_bearer(tmp_path) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    port = httpd.server_address[1]
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        rec = {
            "service_id": "example-app",
            "upstream": f"http://127.0.0.1:{port}",
            "inject_bearer": True,
            "upstream_bearer": "app-secret",
        }
        status, headers, payload = app_gateway.proxy(
            rec,
            method="GET",
            rest_path="health",
            query="",
            req_headers={"Authorization": "Bearer fleet-token", "Accept": "application/json"},
            body=b"",
        )
        assert status == 200
        data = json.loads(payload.decode())
        assert data["auth"] == "Bearer app-secret"
        assert data["path"] == "/health"
        assert "json" in headers.get("Content-Type", "")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_deploy_argv_force_recreate(tmp_path) -> None:
    (tmp_path / "compose.yaml").write_text("name: example\n", encoding="utf-8")
    argv = migration_jobs.build_argv_for_step(
        "deploy_service",
        migration_id="m",
        step_id="s",
        bundle_extracted=None,
        meta={
            "compose_root": str(tmp_path),
            "compose_files": ["compose.yaml"],
            "force_recreate": True,
            "compose_service": "example-app",
        },
    )
    assert "--force-recreate" in argv
    assert "example-app" in argv
    assert "forge-market" not in " ".join(argv)


def test_html_rewrite_prefixes_root_urls() -> None:
    html = (
        b"<!doctype html><html><head></head><body>"
        b'<link href="/ks/theme.css">'
        b'<script src="/assets/app.js"></script>'
        b"</body></html>"
    )
    out = app_gateway._inject_html_prefix(html, "text/html", "/v1/app-gateways/example-app")
    assert b'href="/v1/app-gateways/example-app/ks/theme.css"' in out
    assert b'src="/v1/app-gateways/example-app/assets/app.js"' in out
    assert b"window.__FORGE_API_BASE__=" in out
    assert b"/v1/app-gateways/example-app/v1/app-gateways/" not in out


def test_register_edge_route_completes_in_process(tmp_path) -> None:
    db = tmp_path / "f.sqlite"
    conn = store.connect(db)
    data_dir = tmp_path / "data"
    compose = tmp_path / "compose"
    compose.mkdir()
    (compose / ".env").write_text("", encoding="utf-8")
    mid = store.create_migration(
        conn,
        source_label="test",
        target_label="granite",
        meta={
            "gateway_service_id": "example-app",
            "gateway_upstream": "http://127.0.0.1:19792",
            "compose_root": str(compose),
            "app_bearer_env": "APP_TOKEN",
        },
        step_kinds=["register_edge_route"],
    )
    store.update_migration(conn, mid, bundle_state="ready")
    steps = store.list_migration_steps(conn, mid)
    edge = next(s for s in steps if s.get("kind") == "register_edge_route")
    ok, err = run_migration_step(conn, db, data_dir, mid, str(edge["id"]))
    assert err is None
    assert ok is not None
    assert ok["status"] == "completed"
    assert ok["gateway"]["path"] == "/v1/app-gateways/example-app"
    assert ok["gateway"]["new_tunnel"] is False
    conn.close()


def test_http_gateway_put_and_proxy(tmp_path) -> None:
    import time
    import urllib.request
    from http.server import ThreadingHTTPServer
    from pathlib import Path

    from fleet_server.main import FleetHandler

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    up_thread = Thread(target=upstream.serve_forever, daemon=True)
    up_thread.start()
    up_port = upstream.server_address[1]
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(tmp_path)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = "fleet-token"
    httpd.loopback_bind_skips_auth = False
    httpd.fleet_started_epoch = time.time()
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        req = urllib.request.Request(
            f"{base}/v1/app-gateways/example-app",
            data=json.dumps(
                {
                    "upstream": f"http://127.0.0.1:{up_port}",
                    "inject_bearer": True,
                    "upstream_bearer": "app-secret",
                }
            ).encode(),
            headers={
                "Authorization": "Bearer fleet-token",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            created = json.loads(resp.read().decode())
        assert created["ok"] is True
        assert created["gateway"]["path"] == "/v1/app-gateways/example-app"
        assert "upstream_bearer" not in created["gateway"]
        req2 = urllib.request.Request(
            f"{base}/v1/app-gateways/example-app/health",
            headers={"Authorization": "Bearer fleet-token"},
            method="GET",
        )
        with urllib.request.urlopen(req2, timeout=10) as resp2:
            proxied = json.loads(resp2.read().decode())
        assert proxied["auth"] == "Bearer app-secret"
        assert proxied["path"] == "/health"
    finally:
        httpd.shutdown()
        httpd.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_apply_compose_env_writes_api_only_flag(tmp_path) -> None:
    meta = {
        "compose_root": str(tmp_path),
        "compose_root": str(tmp_path),
        "compose_env": {"FORGE_MARKET_API_ONLY": "1", "INCLUDE_STUDIO_UI": "0"},
    }
    out = app_gateway.apply_compose_env(meta)
    assert out["skipped"] is False
    env = tmp_path / ".env"
    assert app_gateway.read_dotenv_value(env, "FORGE_MARKET_API_ONLY") == "1"
    assert app_gateway.read_dotenv_value(env, "INCLUDE_STUDIO_UI") == "0"
