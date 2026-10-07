"""``update-fleet.sh --remote-upgrade`` must finish without operator action.

Hosts still on a git install channel answer ``migrate_to_apt_required``; the
script falls back to the cooperative git upgrade through the same API, retries
``upgrade_blocked`` once with ``on_timeout=force`` and finally verifies the
version reported by ``/v1/health``.
"""

from __future__ import annotations

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "update-fleet.sh"


def _extract_function(body: str, name: str) -> str:
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"{name}()"):
            end = next(i for i in range(idx + 1, len(lines)) if lines[i] == "}")
            return "\n".join(lines[idx : end + 1])
    raise AssertionError(f"{name} not found in {SCRIPT}")


class _FakeFleet:
    def __init__(self, script: list[tuple[int, dict]], version_after: str) -> None:
        self.posts: list[dict] = []
        self.script = list(script)
        self.version_after = version_after
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a) -> None:  # noqa: D401
                return

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                outer.posts.append(json.loads(self.rfile.read(n) or b"{}"))
                code, payload = outer.script.pop(0) if outer.script else (500, {"ok": False, "error": "exhausted"})
                self._send(code, payload)

            def do_GET(self) -> None:  # noqa: N802
                # The "new" version appears only once every scripted POST was consumed.
                ver = outer.version_after if not outer.script else "0.0.0"
                self._send(200, {"ok": True, "version": {"package_semver": ver}})

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _run(port: int, new_ver: str, *, strict: bool = False) -> subprocess.CompletedProcess:
    body = SCRIPT.read_text(encoding="utf-8")
    funcs = "\n".join(
        _extract_function(body, n) for n in ("remote_upgrade_resolve", "invoke_remote_upgrade", "remote_upgrade_verify")
    )
    prelude = (
        f"PUBLISH_APT_CDN=1\nREMOTE_STRICT_APT={1 if strict else 0}\nNEW_VER={new_ver}\n"
        f"REMOTE_URL_OVERRIDE=http://127.0.0.1:{port}\nREMOTE_BEARER_OVERRIDE=test\n"
        "FLEET_REMOTE_UPGRADE_MAX_WAIT_SEC=1\nFLEET_REMOTE_UPGRADE_VERIFY_SEC=10\n"
    )
    return subprocess.run(
        ["bash", "-c", prelude + funcs + "\ninvoke_remote_upgrade"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_git_channel_host_falls_back_without_operator() -> None:
    fleet = _FakeFleet(
        [
            (400, {"ok": False, "error": "migrate_to_apt_required", "install_channel": "git_user"}),
            (200, {"ok": True, "note": "git pull + restart", "scheduled_restart": True}),
        ],
        version_after="9.9.9",
    )
    try:
        proc = _run(fleet.port, "9.9.9")
    finally:
        fleet.close()
    assert proc.returncode == 0, proc.stderr
    assert fleet.posts[0]["require_apt_channel"] is True
    assert fleet.posts[0]["allow_git_fallback"] is True
    assert "require_apt_channel" not in fleet.posts[1]
    assert "falling back to cooperative git upgrade" in proc.stderr
    assert "remote verified" in proc.stdout


def test_strict_apt_refuses_git_fallback() -> None:
    fleet = _FakeFleet(
        [(400, {"ok": False, "error": "migrate_to_apt_required", "install_channel": "git_user"})],
        version_after="9.9.9",
    )
    try:
        proc = _run(fleet.port, "9.9.9", strict=True)
    finally:
        fleet.close()
    assert proc.returncode != 0
    assert len(fleet.posts) == 1
    assert fleet.posts[0]["allow_git_fallback"] is False
    assert "migrate it" in proc.stderr


def test_upgrade_blocked_retries_with_force_then_verifies() -> None:
    fleet = _FakeFleet(
        [
            (409, {"ok": False, "error": "upgrade_blocked", "waiting_on": [{"service_id": "market-studio"}]}),
            (200, {"ok": True, "note": "forced"}),
        ],
        version_after="1.2.3",
    )
    try:
        proc = _run(fleet.port, "1.2.3")
    finally:
        fleet.close()
    assert proc.returncode == 0, proc.stderr
    assert fleet.posts[1]["on_timeout"] == "force"
    assert "waiting_on" in proc.stderr
    assert "remote verified" in proc.stdout


def test_verify_fails_when_version_never_changes() -> None:
    fleet = _FakeFleet([(200, {"ok": True})], version_after="0.0.1")
    try:
        proc = _run(fleet.port, "0.0.2")
    finally:
        fleet.close()
    assert proc.returncode != 0
    assert "remote verify timed out" in proc.stderr
