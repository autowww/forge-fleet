"""Rollout guards must not hang on a wedged market-studio.

Regression (2026-10-07): prod ``forge-market-app`` accepted TCP connections but
never answered. ``_lifecycle_wait_studio`` used an unbounded ``curl -fsS`` and
blocked for the full 1800s Fleet timeout, so the rollout — the only recovery
path for that container — never reached the restart.
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rollout-forge-market-studio.sh"


def _extract_function(body: str, name: str) -> str:
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"{name}()"):
            end = next(i for i in range(idx + 1, len(lines)) if lines[i] == "}")
            return "\n".join(lines[idx : end + 1])
    raise AssertionError(f"{name} not found in {SCRIPT}")


class _BlackHole:
    """Accepts connections and never writes a byte."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._held: list[socket.socket] = []
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
                self._held.append(conn)
            except socket.timeout:
                continue
            except OSError:
                break

    def close(self) -> None:
        self._stop.set()
        for c in self._held:
            try:
                c.close()
            except OSError:
                pass
        self.sock.close()


def _run_guard(fn: str, port: int, **env: str) -> subprocess.CompletedProcess:
    body = SCRIPT.read_text(encoding="utf-8")
    harness = "\n".join(
        [
            "set -uo pipefail",
            'log() { printf "%s\\n" "$*"; }',
            *(
                _extract_function(body, name)
                for name in ("_studio_curl", "_lifecycle_prepare_studio", "_lifecycle_wait_studio")
            ),
            fn,
        ]
    )
    return subprocess.run(
        ["bash", "-c", harness],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "FORGE_MARKET_STUDIO_HOST_PORT": str(port),
            "FORGE_MARKET_STUDIO_CURL_TIMEOUT_SEC": "1",
            "FORGE_MARKET_STUDIO_CURL_CONNECT_TIMEOUT_SEC": "1",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_lifecycle_wait_gives_up_on_wedged_studio() -> None:
    hole = _BlackHole()
    try:
        started = time.monotonic()
        r = _run_guard("_lifecycle_wait_studio", hole.port, FORGE_MARKET_LIFECYCLE_WAIT_SEC="45")
        elapsed = time.monotonic() - started
    finally:
        hole.close()
    assert r.returncode == 0, r.stderr
    assert "studio wedged; continuing rollout" in r.stdout
    # two bounded probes (1s each) plus one 3s sleep — far below the 45s budget
    assert elapsed < 15, f"lifecycle wait blocked for {elapsed:.1f}s"


def test_lifecycle_prepare_returns_on_wedged_studio() -> None:
    hole = _BlackHole()
    try:
        started = time.monotonic()
        r = _run_guard("_lifecycle_prepare_studio", hole.port)
        elapsed = time.monotonic() - started
    finally:
        hole.close()
    assert r.returncode == 0, r.stderr
    assert "prepare-stop unreachable" in r.stdout
    assert elapsed < 10


def test_every_studio_probe_is_bounded() -> None:
    """No bare ``curl -fsS`` against the studio port may remain in the script."""
    body = SCRIPT.read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in body.splitlines()
        if "curl -fsS" in line
        and ("${port}" in line or '"$url"' in line)
        and "--max-time" not in line
    ]
    assert offenders == [], offenders
