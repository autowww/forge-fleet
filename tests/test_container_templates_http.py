"""HTTP integration: container types, requirement templates, resolve, auth, jobs + template image."""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fleet_server import container_layout, container_templates, store
from fleet_server.main import FleetHandler


def _start_fleet_httpd(
    data_dir: Path,
    *,
    token: str = "",
    loopback_skips_auth: bool = True,
) -> tuple[ThreadingHTTPServer, threading.Thread, int]:
    data_dir.mkdir(parents=True, exist_ok=True)
    db = data_dir / "fleet.sqlite"
    store.connect(db).close()
    container_layout.ensure_layout(data_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FleetHandler)
    httpd.db_path = db
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = "127.0.0.1"
    httpd.expected_token = token
    httpd.loopback_bind_skips_auth = loopback_skips_auth
    httpd.fleet_started_epoch = time.time()
    httpd.fleet_started_utc = ""
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, th, port


def _json_req(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    h = dict(headers or {})
    if data is not None and "Content-Type" not in h:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"_raw": body[:500]}
        return e.code, parsed


def test_get_container_types_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd"
    httpd, th, port = _start_fleet_httpd(data_dir)
    try:
        code, body = _json_req(f"http://127.0.0.1:{port}/v1/container-types")
        assert code == 200
        assert body.get("ok") is True
        paths = body.get("paths") or {}
        for k in ("types_file", "requirement_templates_file", "build_cache_file", "dockerfiles_root", "services_dir"):
            assert k in paths, paths
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)


def test_put_get_templates_resolve_types_crud(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd2"
    httpd, th, port = _start_fleet_httpd(data_dir)
    base = f"http://127.0.0.1:{port}"
    try:
        tmpl = {
            "version": 1,
            "templates": [
                {
                    "id": "tiny_alpine",
                    "title": "Tiny",
                    "kind": "image",
                    "ref": "alpine:3.20",
                    "notes": "",
                    "image_semver": "3.20.0",
                },
            ],
        }
        code, put_body = _json_req(
            f"{base}/v1/container-templates",
            method="PUT",
            data=json.dumps(tmpl).encode(),
        )
        assert code == 200 and put_body.get("ok") is True

        code2, get_t = _json_req(f"{base}/v1/container-templates")
        assert code2 == 200
        rows = get_t.get("templates") or []
        assert len(rows) == 1 and rows[0].get("image_semver") == "3.20.0"

        key, fp = container_templates.bundle_fingerprint(data_dir, ["tiny_alpine"])
        container_templates._record_build_success(data_dir, key, fp, "alpine:3.20", None)  # noqa: SLF001

        code3, res = _json_req(f"{base}/v1/container-templates/resolve?requirements=tiny_alpine&build_if_missing=0")
        assert code3 == 200 and res.get("ok") is True
        assert res.get("image") == "alpine:3.20"

        new_type = {
            "id": "http_test_job",
            "category_id": "job",
            "container_class": "http_test_job",
            "title": "HTTP test",
            "notes": "",
            "requirements": ["tiny_alpine"],
        }
        code4, post_t = _json_req(
            f"{base}/v1/container-types",
            method="POST",
            data=json.dumps(new_type).encode(),
        )
        assert code4 == 201 and post_t.get("ok") is True

        code5, put_one = _json_req(
            f"{base}/v1/container-types/http_test_job",
            method="PUT",
            data=json.dumps({"title": "HTTP test updated", "category_id": "job"}).encode(),
        )
        assert code5 == 200 and put_one.get("ok") is True

        code6, _ = _json_req(f"{base}/v1/container-types/http_test_job", method="DELETE")
        assert code6 == 200

        doc = container_layout.load_types(data_dir)
        ids = {str(t.get("id")) for t in doc.get("types", []) if isinstance(t, dict)}
        assert "http_test_job" not in ids
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)


def test_put_container_types_full_catalog(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd3"
    httpd, th, port = _start_fleet_httpd(data_dir)
    base = f"http://127.0.0.1:{port}"
    try:
        code, cur = _json_req(f"{base}/v1/container-types")
        assert code == 200
        cur["version"] = int(cur.get("version") or 2) + 1
        code2, out = _json_req(
            f"{base}/v1/container-types",
            method="PUT",
            data=json.dumps(cur).encode(),
        )
        assert code2 == 200 and out.get("ok") is True
        assert int(out.get("version") or 0) == cur["version"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)


def test_get_container_templates_requires_bearer_when_configured(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd4"
    httpd, th, port = _start_fleet_httpd(data_dir, token="secret-token", loopback_skips_auth=False)
    try:
        code, _body = _json_req(f"http://127.0.0.1:{port}/v1/container-templates")
        assert code == 401
        code2, body2 = _json_req(
            f"http://127.0.0.1:{port}/v1/container-templates",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert code2 == 200 and body2.get("ok") is True
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)


def test_post_jobs_use_fleet_template_image_rewrites_argv(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd5"
    httpd, th, port = _start_fleet_httpd(data_dir)
    base = f"http://127.0.0.1:{port}"
    try:
        tmpl = {
            "version": 1,
            "templates": [
                {"id": "seed_slug", "title": "S", "kind": "image", "ref": "alpine:3.20", "notes": ""},
            ],
        }
        _json_req(f"{base}/v1/container-templates", method="PUT", data=json.dumps(tmpl).encode())
        key, fp = container_templates.bundle_fingerprint(data_dir, ["seed_slug"])
        container_templates._record_build_success(data_dir, key, fp, "alpine:3.20", None)  # noqa: SLF001

        job_body = {
            "kind": "docker_argv",
            "argv": ["docker", "run", "-e", "FLEET_TEST=1", "placeholder:never-pulled", "true"],
            "session_id": "tpl-test",
            "meta": {
                "container_class": "http_test_job",
                "use_fleet_template_image": True,
                "requirements": ["seed_slug"],
                "build_template_if_missing": False,
            },
        }
        code, created = _json_req(
            f"{base}/v1/jobs",
            method="POST",
            data=json.dumps(job_body).encode(),
        )
        assert code == 201 and created.get("ok") is True
        jid = created["id"]
        conn = store.connect(httpd.db_path)
        try:
            row = store.get_job(conn, jid)
            assert row is not None
            argv = row.get("argv") or []
            assert "alpine:3.20" in argv
            assert "placeholder:never-pulled" not in argv
        finally:
            conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)


@pytest.mark.skipif(not shutil.which("docker"), reason="docker CLI not available")
def test_post_container_templates_build_alpine_image(tmp_path: Path) -> None:
    data_dir = tmp_path / "fd6"
    httpd, th, port = _start_fleet_httpd(data_dir)
    base = f"http://127.0.0.1:{port}"
    try:
        tmpl = {
            "version": 1,
            "templates": [
                {"id": "pull_me", "title": "P", "kind": "image", "ref": "alpine:3.20", "notes": ""},
            ],
        }
        _json_req(f"{base}/v1/container-templates", method="PUT", data=json.dumps(tmpl).encode())
        code, out = _json_req(
            f"{base}/v1/container-templates/build",
            method="POST",
            data=json.dumps({"requirement_ids": ["pull_me"]}).encode(),
        )
        assert code == 200, out
        assert out.get("ok") is True
        assert out.get("image")
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)
