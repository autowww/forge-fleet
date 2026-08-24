"""HTTP tests for GW-2 migration API (/v1/migrations)."""

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
from fleet_server.migrations import MIGRATION_MANIFEST_FILENAME
from fleet_server.workspace_bundle import WORKSPACE_PROFILES


def _migration_tar_gz(flags: dict[str, bool], extra_files: dict[str, bytes] | None = None) -> bytes:
    manifest = {
        "schema_version": 1,
        "flags": flags,
        "inventory_bytes": 12,
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:gz") as tf:
        for path, content in sorted((extra_files or {}).items()):
            ti = tarfile.TarInfo(name=path)
            ti.size = len(content)
            tf.addfile(ti, io.BytesIO(content))
        ti = tarfile.TarInfo(name=MIGRATION_MANIFEST_FILENAME)
        ti.size = len(manifest_bytes)
        tf.addfile(ti, io.BytesIO(manifest_bytes))
        payload = b"corpus-payload"
        ti2 = tarfile.TarInfo(name="data/corpus.bin")
        ti2.size = len(payload)
        tf.addfile(ti2, io.BytesIO(payload))
    return bio.getvalue()


def _start_fleet_httpd(data_dir: Path) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
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
    return httpd, th, f"http://127.0.0.1:{port}"


def _stop_fleet_httpd(httpd: ThreadingHTTPServer, th: threading.Thread) -> None:
    httpd.shutdown()
    httpd.server_close()
    th.join(timeout=10)


def test_migration_bundle_profile_limits() -> None:
    prof = WORKSPACE_PROFILES["migration_bundle"]
    assert prof["max_uncompressed_bytes"] == 2 * 1024 * 1024 * 1024
    assert prof["container_mount"] == "/migration/bundle"


def test_store_migration_crud(tmp_path: Path) -> None:
    db = tmp_path / "m.sqlite"
    conn = store.connect(db)
    try:
        mid = store.create_migration(
            conn,
            source_label="local",
            target_label="granite",
            step_kinds=["seed_corpus_volume", "migrate_db"],
        )
        row = store.get_migration(conn, mid)
        assert row is not None
        assert row["status"] == "pending"
        assert len(row["steps"]) == 2
        step_id = str(row["steps"][0]["id"])
        store.update_step(conn, step_id, status="queued", job_id="job123")
        steps = store.list_migration_steps(conn, mid)
        assert steps[0]["status"] == "queued"
        assert store.cancel_migration(conn, mid)
        row2 = store.get_migration(conn, mid)
        assert row2 and row2["status"] == "cancelled"
    finally:
        conn.close()


def test_post_get_migration_session(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        body = json.dumps(
            {"source_label": "dev-laptop", "target_label": "granite-staging", "meta": {"recipe": "market"}}
        ).encode()
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        assert resp.status == 201
        assert created.get("ok") is True
        mid = created["id"]
        assert created["bundle_state"] == "pending_upload"
        assert len(created.get("steps") or []) >= 5

        req2 = urllib.request.Request(f"{base}/v1/migrations/{mid}", method="GET")
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            got = json.loads(resp2.read().decode())
        assert got["ok"] is True
        assert got["id"] == mid
        assert got["source_label"] == "dev-laptop"
        assert "bytes_transferred" in got
    finally:
        _stop_fleet_httpd(httpd, th)


def test_put_data_bundle_and_manifest_flags(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd2"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({"source_label": "a", "target_label": "b"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        mid = created["id"]
        blob = _migration_tar_gz({"corpus": True, "raw_sec": False, "broker": False, "wiki": False})
        sha = hashlib.sha256(blob).hexdigest()
        req2 = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/data-bundle",
            data=blob,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(blob)),
                "X-Migration-Bundle-Sha256": sha,
            },
            method="PUT",
        )
        with urllib.request.urlopen(req2, timeout=60) as resp2:
            up = json.loads(resp2.read().decode())
        assert up["ok"] is True
        assert up["bundle_state"] == "ready"
        assert up["bundle_sha256"] == sha
        assert up["manifest"]["flags"]["corpus"] is True
        kinds = {s["kind"]: s["status"] for s in up["steps"]}
        assert kinds.get("seed_corpus_volume") == "pending"
        assert kinds.get("migrate_db") == "skipped"
    finally:
        _stop_fleet_httpd(httpd, th)


def test_post_migration_step_run_queues_job(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd3"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({"source_label": "a", "target_label": "b"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        mid = created["id"]
        blob = _migration_tar_gz({"corpus": True, "raw_sec": True, "broker": False, "wiki": False})
        req_up = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/data-bundle",
            data=blob,
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(blob))},
            method="PUT",
        )
        with urllib.request.urlopen(req_up, timeout=60) as resp_up:
            json.loads(resp_up.read().decode())

        step_id = None
        for s in created["steps"]:
            if s["kind"] == "build_image":
                step_id = s["id"]
                break
        assert step_id
        req_run = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/steps/{step_id}/run",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_run, timeout=30) as resp_run:
            run_out = json.loads(resp_run.read().decode())
        assert run_out["ok"] is True
        jid = run_out["job_id"]
        db = data_dir / "fleet.sqlite"
        conn = store.connect(db)
        try:
            job = store.get_job(conn, jid)
            assert job is not None
            assert job["kind"] == "docker_argv"
            meta = job.get("meta") or {}
            assert meta.get("migration_id") == mid
            assert meta.get("migration_step_kind") == "build_image"
        finally:
            conn.close()
    finally:
        _stop_fleet_httpd(httpd, th)


def test_cancel_migration(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd4"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        mid = created["id"]
        req_cancel = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/cancel",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_cancel, timeout=30) as resp_cancel:
            out = json.loads(resp_cancel.read().decode())
        assert out["ok"] is True
        assert out["status"] == "cancelled"
    finally:
        _stop_fleet_httpd(httpd, th)


def test_chunked_data_bundle_upload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_MIGRATION_CHUNK_SIZE_BYTES", "4096")
    data_dir = tmp_path / "fd6"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({"source_label": "chunk", "target_label": "granite"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        mid = created["id"]
        blob = _migration_tar_gz({"corpus": True, "raw_sec": False, "broker": False, "wiki": False})
        sha = hashlib.sha256(blob).hexdigest()
        chunk_size = 4096
        chunk_count = (len(blob) + chunk_size - 1) // chunk_size

        sess_req = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/data-bundle/upload-session",
            data=json.dumps(
                {"sha256": sha, "total_bytes": len(blob), "chunk_size": chunk_size}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(sess_req, timeout=30) as resp_sess:
            sess = json.loads(resp_sess.read().decode())
        assert sess.get("ok") is True
        assert sess["chunk_count"] == chunk_count

        for idx in range(chunk_count):
            start = idx * chunk_size
            end = min(start + chunk_size, len(blob))
            chunk = blob[start:end]
            chunk_req = urllib.request.Request(
                f"{base}/v1/migrations/{mid}/data-bundle/chunks/{idx}",
                data=chunk,
                headers={"Content-Type": "application/octet-stream", "Content-Length": str(len(chunk))},
                method="PUT",
            )
            with urllib.request.urlopen(chunk_req, timeout=30) as resp_chunk:
                out = json.loads(resp_chunk.read().decode())
            assert out.get("ok") is True

        fin_req = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/data-bundle/finalize",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(fin_req, timeout=60) as resp_fin:
            up = json.loads(resp_fin.read().decode())
        assert up.get("ok") is True
        assert up["bundle_state"] == "ready"
        assert up["bundle_sha256"] == sha
        assert up.get("upload_mode") == "chunked"
    finally:
        _stop_fleet_httpd(httpd, th)


def test_run_step_before_bundle_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd5"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        mid = created["id"]
        step_id = created["steps"][0]["id"]
        req_run = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/steps/{step_id}/run",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_run, timeout=30)
        assert exc_info.value.code == 400
        body = json.loads(exc_info.value.read().decode())
        assert body.get("error") == "bundle_not_ready"
    finally:
        _stop_fleet_httpd(httpd, th)


def test_extract_uncompressed_limit_returns_recovery_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "fleet_server.migrations.migration_bundle_limits.max_bundle_uncompressed_bytes",
        lambda row=None: 80,
    )
    data_dir = tmp_path / "fd-unc"
    data_dir.mkdir()
    httpd, th, base = _start_fleet_httpd(data_dir)
    try:
        req = urllib.request.Request(
            f"{base}/v1/migrations",
            data=json.dumps({"source_label": "forge-market", "meta": {"app_slug": "forge-market"}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            created = json.loads(resp.read().decode())
        assert created.get("bundle_uncompressed_max_bytes") == 80
        mid = created["id"]
        blob = _migration_tar_gz(
            {"corpus": True, "raw_sec": False, "broker": False, "wiki": False},
            extra_files={"data/big.bin": b"x" * 200},
        )
        req2 = urllib.request.Request(
            f"{base}/v1/migrations/{mid}/data-bundle",
            data=blob,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(blob)),
            },
            method="PUT",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req2, timeout=60)
        assert exc_info.value.code == 400
        body = json.loads(exc_info.value.read().decode())
        assert body.get("error") == "extract_failed"
        assert body.get("detail") == "uncompressed_size_exceeded"
        assert body.get("recovery_code") == "uncompressed_size_exceeded"
        assert body.get("max_uncompressed_bytes") == 80
    finally:
        _stop_fleet_httpd(httpd, th)
