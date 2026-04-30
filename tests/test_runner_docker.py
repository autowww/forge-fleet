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


def test_inject_fleet_job_id_after_docker_run() -> None:
    argv = ["docker", "run", "--rm", "-e", "FOO=1", "img", "sh", "-c", "true"]
    out = runner._inject_fleet_job_id_for_docker_run(argv, "abc123")
    assert out[:4] == ["docker", "run", "-e", "FLEET_JOB_ID=abc123"]
    assert "--rm" in out and "img" in out
