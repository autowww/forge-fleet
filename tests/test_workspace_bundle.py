"""Workspace tarball staging and HTTP PUT /v1/jobs/{id}/workspace."""

from __future__ import annotations

import hashlib
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
    WORKSPACE_MANIFEST_FILENAME,
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


def _tar_gz_with_manifest(files: dict[str, bytes], manifest: dict[str, object]) -> bytes:
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tf:
        for path, content in sorted(files.items()):
            ti = tarfile.TarInfo(name=path)
            ti.size = len(content)
            tf.addfile(ti, io.BytesIO(content))
        ti = tarfile.TarInfo(name=WORKSPACE_MANIFEST_FILENAME)
        ti.size = len(manifest_bytes)
        tf.addfile(ti, io.BytesIO(manifest_bytes))
    return bio.getvalue()


def test_profile_large_workspace_limits() -> None:
    prof = profile_for_meta({"workspace_profile": "large_workspace"})
    assert prof["profile_id"] == "large_workspace"
    assert prof["max_uncompressed_bytes"] == 500 * 1024 * 1024
    assert prof["container_mount"] == "/workspace"


def test_extract_archive_simple_ok(tmp_path: Path) -> None:
    data = _tiny_tar_gz()
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err, mver, mschema = extract_archive_simple(
        data, data_dir=tmp_path, job_id="a" * 32, profile=prof
    )
    assert err is None
    assert unc >= 2
    assert len(sha) == 64
    assert mver == 0 and mschema is None
    root = tmp_path / "job-workspaces" / ("a" * 32) / "extracted"
    assert (root / "a" / "hello.txt").read_bytes() == b"hi"


def test_extract_manifest_verifies(tmp_path: Path) -> None:
    content = b"payload-bytes"
    h = hashlib.sha256(content).hexdigest()
    data = _tar_gz_with_manifest(
        {"x/y.txt": content},
        {"schema_version": 1, "files": [{"path": "x/y.txt", "size": len(content), "sha256": h}]},
    )
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err, mver, mschema = extract_archive_simple(
        data, data_dir=tmp_path, job_id="c" * 32, profile=prof
    )
    assert err is None
    assert mver == 1 and mschema == 1
    root = tmp_path / "job-workspaces" / ("c" * 32) / "extracted"
    assert (root / "x" / "y.txt").read_bytes() == content


def test_extract_manifest_sha_mismatch_fails(tmp_path: Path) -> None:
    content = b"payload-bytes"
    bad = "0" * 64
    data = _tar_gz_with_manifest(
        {"x/y.txt": content},
        {"schema_version": 1, "files": [{"path": "x/y.txt", "size": len(content), "sha256": bad}]},
    )
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err, mver, mschema = extract_archive_simple(
        data, data_dir=tmp_path, job_id="d" * 32, profile=prof
    )
    assert err and err.startswith("manifest_verification_failed")
    assert mver == 0


def test_extract_manifest_required_missing(tmp_path: Path) -> None:
    data = _tiny_tar_gz()
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err, mver, mschema = extract_archive_simple(
        data,
        data_dir=tmp_path,
        job_id="e" * 32,
        profile=prof,
        manifest_required=True,
    )
    assert err == "manifest_required_but_missing"


def test_extract_rejects_zip_bomb_style_depth(tmp_path: Path) -> None:
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w") as tf:
        long = "/".join(["d"] * 60) + "/x.txt"
        ti = tarfile.TarInfo(name=long)
        ti.size = 1
        tf.addfile(ti, io.BytesIO(b"x"))
    data = bio.getvalue()
    prof = profile_for_meta({"workspace_profile": "generic"})
    unc, sha, err, *_ = extract_archive_simple(data, data_dir=tmp_path, job_id="b" * 32, profile=prof)
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
            up = json.loads(resp2.read().decode())
        assert up.get("manifest_files_verified") == 0
        assert up.get("workspace_sha256") == hashlib.sha256(blob).hexdigest()
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


def test_put_workspace_archive_sha_header_mismatch(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd_hdr"
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
                "session_id": "t-ws2",
                "meta": {"workspace_upload_required": True, "workspace_profile": "generic"},
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
        blob = _tiny_tar_gz()
        wrong = "f" * 64
        req2 = urllib.request.Request(
            f"{base}/v1/jobs/{jid}/workspace",
            data=blob,
            headers={
                "Content-Length": str(len(blob)),
                "X-Workspace-Archive-Sha256": wrong,
            },
            method="PUT",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req2, timeout=30)
        assert ei.value.code == 400
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
