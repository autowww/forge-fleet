"""Tests for remote Fleet peer registry and proxy."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from fleet_server import remote_peers, store
from fleet_server.main import FleetHandler


def test_upsert_list_delete_peer(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    out = remote_peers.upsert_peer(
        data_dir,
        "granite",
        label="Granite",
        base_url="https://granite.example/v1",
        bearer_token="secret-token",
    )
    assert out["ok"] is True
    assert out["created"] is True
    listed = remote_peers.list_peers(data_dir)
    assert len(listed["peers"]) == 1
    assert listed["peers"][0]["base_url"] == "https://granite.example"
    assert listed["peers"][0]["bearer_configured"] is True
    assert "bearer_token" not in listed["peers"][0]

    deleted = remote_peers.delete_peer(data_dir, "granite")
    assert deleted["ok"] is True
    assert remote_peers.list_peers(data_dir)["peers"] == []


def test_proxy_get_unknown_peer(tmp_path: Path) -> None:
    code, body, _ctype = remote_peers.proxy_get(tmp_path, "missing", "/v1/health")
    assert code == 404
    payload = json.loads(body.decode("utf-8"))
    assert payload["error"] == "not_found"


def test_proxy_forwards_bearer(tmp_path: Path) -> None:
    remote_peers.upsert_peer(
        tmp_path,
        "peer1",
        label="P",
        base_url="https://upstream.example",
        bearer_token="tok-abc",
    )
    captured: dict[str, str] = {}

    class FakeResp:
        status = 200

        def read(self) -> bytes:
            return b'{"ok":true}'

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        @property
        def headers(self):
            return {"Content-Type": "application/json"}

    def fake_urlopen(req, timeout=30, context=None):  # noqa: ARG001
        captured["auth"] = req.headers.get("Authorization", "")
        captured["url"] = req.full_url
        return FakeResp()

    with patch("urllib.request.urlopen", fake_urlopen):
        code, body, _ = remote_peers.proxy_get(tmp_path, "peer1", "/v1/admin/snapshot", query="jobs_limit=5")
    assert code == 200
    assert captured["auth"] == "Bearer tok-abc"
    assert captured["url"].endswith("/v1/admin/snapshot?jobs_limit=5")


def test_proxy_routes_forward_paths(tmp_path: Path) -> None:
    remote_peers.upsert_peer(
        tmp_path,
        "peer1",
        label="P",
        base_url="https://upstream.example",
        bearer_token="tok-abc",
    )
    captured: dict[str, str] = {}

    class FakeResp:
        status = 200

        def read(self) -> bytes:
            return b'{"ok":true}'

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        @property
        def headers(self):
            return {"Content-Type": "application/json"}

    def fake_urlopen(req, timeout=30, context=None):  # noqa: ARG001
        captured["url"] = req.full_url
        return FakeResp()

    routes = [
        ("/v1/jobs/job-abc", "/v1/remote-peers/peer1/jobs/job-abc"),
        ("/v1/container-types", "/v1/remote-peers/peer1/container-types"),
        ("/v1/container-templates", "/v1/remote-peers/peer1/container-templates"),
        ("/v1/fleet-apps/my-app/about", "/v1/remote-peers/peer1/fleet-apps/my-app/about"),
    ]
    with patch("urllib.request.urlopen", fake_urlopen):
        for upstream, _proxy_suffix in routes:
            captured.clear()
            code, _body, _ = remote_peers.proxy_get(tmp_path, "peer1", upstream)
            assert code == 200
            assert captured["url"].endswith(upstream)


def test_remote_peers_http_proxy_routes(tmp_path: Path) -> None:
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

    def req_get(path: str) -> tuple[int, dict]:
        r = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            method="GET",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    remote_peers.upsert_peer(
        data_dir,
        "granite",
        label="Granite",
        base_url="https://granite.example",
        bearer_token="x",
    )

    try:
        with patch.object(remote_peers, "_request_peer") as mock_req:
            mock_req.return_value = (200, b'{"ok":true}', "application/json")
            code, payload = req_get("/v1/remote-peers/granite/jobs/job-1")
            assert code == 200
            assert payload.get("ok") is True
            assert mock_req.call_args[0][1] == "/v1/jobs/job-1"

            code, payload = req_get("/v1/remote-peers/granite/container-types")
            assert code == 200
            assert mock_req.call_args[0][1] == "/v1/container-types"

        code, payload = req_get("/v1/remote-peers/missing/jobs/job-1")
        assert code == 404
        assert payload.get("error") == "not_found"
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)


def test_remote_peers_http_crud(tmp_path: Path) -> None:
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

    def req(method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        r = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read().decode("utf-8"))

    try:
        put = req(
            "PUT",
            "/v1/remote-peers/granite",
            {"label": "Granite", "base_url": "https://granite.example", "bearer_token": "x"},
        )
        assert put.get("ok") is True
        listed = req("GET", "/v1/remote-peers")
        assert any(p.get("id") == "granite" for p in listed.get("peers", []))
        deleted = req("DELETE", "/v1/remote-peers/granite")
        assert deleted.get("ok") is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)
