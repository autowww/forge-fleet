"""Docker argv resolution for systemd / Snap PATH quirks."""

from __future__ import annotations

from fleet_server import runner


def test_resolve_argv_docker_respects_fleet_docker_bin(monkeypatch) -> None:
    monkeypatch.setenv("FLEET_DOCKER_BIN", "/opt/bin/docker")
    monkeypatch.delenv("PATH", raising=False)
    out = runner._resolve_argv_docker(["docker", "run", "--rm", "alpine"])
    assert out[0] == "/opt/bin/docker"
    assert out[1:] == ["run", "--rm", "alpine"]


def test_resolve_argv_passes_through_non_docker() -> None:
    assert runner._resolve_argv_docker(["/bin/true"]) == ["/bin/true"]
