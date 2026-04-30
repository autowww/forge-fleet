"""Workspace tarball staging and HTTP PUT /v1/jobs/{id}/workspace."""

from __future__ import annotations

import gzip
import io
import json
import tarfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fleet_server import store
from fleet_server.main import FleetHandler
from fleet_server.workspace_bundle import (
    extract_archive_simple,
    inject_workspace_bind_mount,
    profile_for_meta,
)


def _tiny_tar_gz(payload_path: str = "a/hello.txt", content: bytes = b"hi") -> bytes:
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tf:
        ti = tarfile.TarInfo(name=payload_path)
        ti.size = len(content)
        tf.addfile(ti, io.BytesIO(content))
    return bio.getvalue()


def test_extract_archive_simple_ok(tmp_path: Path) -> None:
    data = _tiny_tar_gz()
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err = extract_archive_simple(data, data_dir=tmp_path, job_id="a" * 32, profile=prof)
    assert err is None
    assert unc >= 2
    assert len(sha) == 64
    root = tmp_path / "job-workspaces" / ("a" * 32) / "extracted"
    assert (root / "a" / "hello.txt").read_bytes() == b"hi"


def test_extract_rejects_zip_bomb_style_depth(tmp_path: Path) -> None:
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w") as tf:
        long = "/".join(["d"] * 60) + "/x.txt"
        ti = tarfile.TarInfo(name=long)
        ti.size = 1
        tf.addfile(ti, io.BytesIO(b"x"))
    data = bio.getvalue()
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err = extract_archive_simple(data, data_dir=tmp_path, job_id="b" * 32, profile=prof)
    assert err == "path_too_deep"
    assert unc == 0


def test_inject_workspace_bind_mount_inserts_after_run() -> None:
    argv = ["docker", "run", "--rm", "img"]
    host = Path("/tmp/ws/extracted").resolve()
    out = inject_workspace_bind_mount(argv, host_extracted=host, container_mount="/workspace")
    assert out[:5] == ["docker", "run", "-v", f"{host}:/workspace:ro", "--rm"]


def test_put_workspace_then_job_spawns(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd"
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
        base = f"http://127.0.0.1:{port}"
        body = json.dumps(
            {
                "kind": "docker_argv",
                "argv": ["docker", "run", "--rm", "alpine:latest", "echo", "ok"],
                "session_id": "t-ws",
                "meta": {
                    "workspace_upload_required": True,
                    "workspace_profile": "generic",
                    "container_class": "test",
                },
            }
        ).encode()
        req = urllib.request.Request(
            f"{base}/v1/jobs",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        jid = created["id"]
        conn = store.connect(db)
        try:
            row = store.get_job(conn, jid)
            assert row and row["status"] == "queued"
            m = row.get("meta") or {}
            assert m.get("workspace_state") == "pending_upload"
        finally:
            conn.close()

        blob = _tiny_tar_gz()
        req2 = urllib.request.Request(
            f"{base}/v1/jobs/{jid}/workspace",
            data=blob,
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(blob))},
            method="PUT",
        )
        with urllib.request.urlopen(req2, timeout=60) as resp2:
            assert resp2.status == 200
        time.sleep(0.3)
        conn = store.connect(db)
        try:
            row2 = store.get_job(conn, jid)
            assert row2
            assert row2["meta"].get("workspace_state") == "ready"
        finally:
            conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)


def test_put_workspace_requires_auth(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd2"
    data_dir.mkdir()
    db = data_dir / "fleet.sqlite"
    store.connect(db).close()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = "secret"
    httpd.loopback_bind_skips_auth = False
    httpd.fleet_started_epoch = time.time()
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{port}"
        body = json.dumps(
            {
                "kind": "docker_argv",
                "argv": ["echo", "x"],
                "session_id": "t",
                "meta": {"workspace_upload_required": True},
            }
        ).encode()
        req = urllib.request.Request(
            f"{base}/v1/jobs",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer secret",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        jid = created["id"]
        blob = _tiny_tar_gz()
        req2 = urllib.request.Request(
            f"{base}/v1/jobs/{jid}/workspace",
            data=blob,
            headers={"Content-Length": str(len(blob))},
            method="PUT",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req2, timeout=30)
        assert ei.value.code == 401
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=10)
