"""Real Docker integration: Fleet worker runs ``docker run`` on the host daemon.

Skipped automatically when the Docker CLI is missing or ``docker info`` fails (no daemon,
permission denied on the socket, etc.). Set ``SKIP_DOCKER_INTEGRATION=1`` to force skip.

Run explicitly::

    cd forge-fleet && python3 -m pytest tests/test_fleet_docker_integration.py -v

Optional image override::

    FLEET_DOCKER_INTEGRATION_IMAGE=busybox:stable python3 -m pytest tests/test_fleet_docker_integration.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fleet_server import store
from fleet_server.main import FleetHandler


def _docker_daemon_usable() -> bool:
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return False
    try:
        r = subprocess.run(
            [docker_bin, "info"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _fleet_integration_image() -> str:
    return (os.environ.get("FLEET_DOCKER_INTEGRATION_IMAGE") or "alpine:3.19").strip()


requires_docker = pytest.mark.skipif(
    os.environ.get("SKIP_DOCKER_INTEGRATION", "").strip().lower() in ("1", "true", "yes"),
    reason="SKIP_DOCKER_INTEGRATION is set",
)


@pytest.fixture
def docker_available() -> None:
    if not shutil.which("docker"):
        pytest.skip("docker CLI not on PATH")
    if not _docker_daemon_usable():
        pytest.skip("docker daemon not reachable (docker info failed)")


def _poll_job_json(base: str, jid: str, *, timeout_s: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        req = urllib.request.Request(f"{base}/v1/jobs/{jid}", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                last = json.loads(resp.read().decode())
        except urllib.error.HTTPError:
            time.sleep(0.2)
            continue
        st = str(last.get("status") or "").strip().lower()
        if st in ("completed", "failed", "cancelled"):
            return last
        time.sleep(0.25)
    raise AssertionError(f"job {jid} did not finish within {timeout_s}s; last={last!r}")


@pytest.mark.integration
@requires_docker
def test_fleet_runs_docker_container_echo(tmp_path: Path, docker_available: None) -> None:
    """POST docker_argv → runner spawns ``docker run`` → job completes with expected stdout."""
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

    img = _fleet_integration_image()
    marker = "fleet-docker-integration-ok"
    argv = [
        "docker",
        "run",
        "--rm",
        img,
        "sh",
        "-c",
        f"echo {marker}",
    ]

    base = f"http://127.0.0.1:{port}"
    body = json.dumps(
        {
            "kind": "docker_argv",
            "argv": argv,
            "session_id": "integration-docker",
            "meta": {"container_class": "integration_test"},
        }
    ).encode()
    try:
        req = urllib.request.Request(
            f"{base}/v1/jobs",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            created = json.loads(resp.read().decode())
        jid = created["id"]

        final = _poll_job_json(base, jid, timeout_s=240.0)
        assert final.get("status") == "completed", (
            f"job failed: status={final.get('status')!r} exit_code={final.get('exit_code')!r} "
            f"stderr={final.get('stderr', '')[:2000]!r}"
        )
        # Do not use `... or 1`: exit code 0 is falsy in Python.
        exit_code = final.get("exit_code")
        assert exit_code is not None
        assert int(exit_code) == 0
        out = str(final.get("stdout") or "")
        assert marker in out, f"stdout missing marker: {out!r}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        th.join(timeout=15)
