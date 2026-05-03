"""Remote Forge Fleet E2E: container-templates API + docker_argv job (optional).

Requires a reachable Fleet base URL and admin bearer (same env names as forge-certificators).

**Does not** ship client-specific templates: the test registers a disposable ``kind: image`` row
pointing at public ``alpine``, builds/pulls via ``POST /v1/container-templates/build``, queues a
``docker_argv`` job with ``meta.use_fleet_template_image``, polls ``GET /v1/jobs/{id}``, then
removes its template row via ``PUT`` (merge from GET).

Run::

    export RUN_REMOTE_FLEET_CONTAINER_API_E2E=1
    export FORGE_FLEET_BASE_URL=https://your-fleet.example      # origin only, no /v1
    export FORGE_FLEET_BEARER_TOKEN=...
    cd forge-fleet && PYTHONPATH=. python3 -m pytest tests/test_remote_fleet_container_templates_e2e.py -v

Optional: ``FLEET_REMOTE_E2E_IMAGE=alpine:3.20`` (default ``alpine:3.20``).

Skip with ``SKIP_REMOTE_FLEET_CONTAINER_API_E2E=1`` or when env is unset.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request
from typing import Any

import pytest

_RUN = os.environ.get("RUN_REMOTE_FLEET_CONTAINER_API_E2E", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
_SKIP = os.environ.get("SKIP_REMOTE_FLEET_CONTAINER_API_E2E", "").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _origin() -> str:
    raw = (os.environ.get("FORGE_FLEET_BASE_URL") or "").strip().rstrip("/")
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw.rstrip("/")


def _bearer() -> str:
    return (os.environ.get("FORGE_FLEET_BEARER_TOKEN") or "").strip()


def _e2e_image() -> str:
    return (os.environ.get("FLEET_REMOTE_E2E_IMAGE") or "alpine:3.20").strip()


def _req(
    method: str,
    url: str,
    *,
    bearer: str,
    body: dict[str, Any] | None = None,
    timeout_s: float = 300.0,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {bearer}",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode() or 200
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        code = e.code
    try:
        parsed: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        parsed = {"_raw": raw[:2000]}
    return code, parsed if isinstance(parsed, dict) else {"_raw": str(parsed)}


def _poll_job(base: str, bearer: str, jid: str, *, timeout_s: float = 240.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    url = f"{base}/v1/jobs/{jid}"
    while time.monotonic() < deadline:
        code, last = _req("GET", url, bearer=bearer, timeout_s=60.0)
        if code != 200:
            time.sleep(0.3)
            continue
        st = str(last.get("status") or "").strip().lower()
        if st in ("completed", "failed", "cancelled"):
            return last
        time.sleep(0.35)
    raise AssertionError(f"job {jid} did not finish within {timeout_s}s; last={last!r}")


def _valid_template_id() -> str:
    """Fleet requirement id: ``^[a-z][a-z0-9_-]{0,63}$``."""
    suf = uuid.uuid4().hex[:10]
    return f"e2e_{suf}"


@pytest.mark.integration
@pytest.mark.skipif(_SKIP, reason="SKIP_REMOTE_FLEET_CONTAINER_API_E2E is set")
@pytest.mark.skipif(not _RUN, reason="set RUN_REMOTE_FLEET_CONTAINER_API_E2E=1 to run")
@pytest.mark.skipif(not _origin() or not _bearer(), reason="FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN required")
def test_remote_fleet_container_templates_api_and_docker_job() -> None:
    origin = _origin()
    bearer = _bearer()
    img = _e2e_image()
    tid = _valid_template_id()
    marker = f"remote-fleet-e2e-{tid}"

    code0, health = _req("GET", f"{origin}/v1/health", bearer=bearer)
    assert code0 == 200, health
    assert health.get("ok") is True, health

    code_g0, cur_doc = _req("GET", f"{origin}/v1/container-templates", bearer=bearer)
    assert code_g0 == 200 and cur_doc.get("ok") is True, cur_doc
    prev_templates = [
        t for t in (cur_doc.get("templates") or []) if isinstance(t, dict) and str(t.get("id")) != tid
    ]
    version = int(cur_doc.get("version") or 1)

    new_row = {
        "id": tid,
        "title": "Remote E2E disposable (alpine)",
        "kind": "image",
        "ref": img,
        "notes": "Created by tests/test_remote_fleet_container_templates_e2e.py; safe to delete.",
    }
    put_doc = {"version": version, "templates": prev_templates + [new_row]}
    try:
        code_put, put_out = _req(
            "PUT",
            f"{origin}/v1/container-templates",
            bearer=bearer,
            body=put_doc,
        )
        assert code_put == 200 and put_out.get("ok") is True, put_out

        code_b, build_out = _req(
            "POST",
            f"{origin}/v1/container-templates/build",
            bearer=bearer,
            body={"requirement_ids": [tid]},
            timeout_s=600.0,
        )
        assert code_b == 200 and build_out.get("ok") is True, build_out
        resolved_image = str(build_out.get("image") or "").strip()
        assert resolved_image, build_out

        code_r, res_out = _req(
            "GET",
            f"{origin}/v1/container-templates/resolve?requirements={tid}&build_if_missing=0",
            bearer=bearer,
        )
        assert code_r == 200 and res_out.get("ok") is True, res_out
        assert str(res_out.get("image") or "").strip() == resolved_image

        job_body = {
            "kind": "docker_argv",
            "argv": [
                "docker",
                "run",
                "--rm",
                "-e",
                "FLEET_REMOTE_E2E=1",
                "e2e-placeholder:never-pulled",
                "sh",
                "-c",
                f"echo {marker}",
            ],
            "session_id": f"remote-e2e-{tid}",
            "meta": {
                "container_class": "remote_e2e",
                "use_fleet_template_image": True,
                "requirements": [tid],
                "build_template_if_missing": False,
            },
        }
        code_j, created = _req("POST", f"{origin}/v1/jobs", bearer=bearer, body=job_body)
        assert code_j == 201 and created.get("ok") is True, created
        jid = str(created.get("id") or "").strip()
        assert len(jid) == 32 and re.match(r"^[0-9a-f]{32}$", jid), created

        final = _poll_job(origin, bearer, jid, timeout_s=300.0)
        assert final.get("status") == "completed", (
            f"status={final.get('status')!r} exit_code={final.get('exit_code')!r} "
            f"stderr={str(final.get('stderr') or '')[:4000]!r}"
        )
        ex = final.get("exit_code")
        assert ex is not None
        assert int(ex) == 0
        assert marker in str(final.get("stdout") or ""), final.get("stdout")
    finally:
        code_g1, after = _req("GET", f"{origin}/v1/container-templates", bearer=bearer)
        if code_g1 != 200 or not isinstance(after.get("templates"), list):
            return
        cleaned = [t for t in after["templates"] if isinstance(t, dict) and str(t.get("id")) != tid]
        ver2 = int(after.get("version") or version)
        _req(
            "PUT",
            f"{origin}/v1/container-templates",
            bearer=bearer,
            body={"version": ver2, "templates": cleaned},
        )
