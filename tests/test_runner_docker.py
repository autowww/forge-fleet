"""Docker argv resolution for systemd / Snap PATH quirks."""

from __future__ import annotations

import pytest

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


def test_inject_host_metrics_env_after_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER", "1")
    monkeypatch.setenv("FLEET_HOST_METRICS_BASE_URL", "http://172.17.0.1:18766")
    monkeypatch.setenv("FLEET_BEARER_TOKEN", "secret-bearer")
    argv = ["docker", "run", "--rm", "img", "true"]
    out = runner._inject_host_metrics_client_env_for_docker_run(
        runner._inject_fleet_job_id_for_docker_run(argv, "job-uuid-1")
    )
    assert out[:4] == ["docker", "run", "-e", "FLEET_JOB_ID=job-uuid-1"]
    i_url = out.index("FLEET_HOST_METRICS_URL=http://172.17.0.1:18766")
    assert out[i_url - 1] == "-e"
    assert "FLEET_HOST_METRICS_TOKEN=secret-bearer" in out


def test_inject_host_metrics_skips_token_when_bearer_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER", "1")
    monkeypatch.setenv("FLEET_HOST_METRICS_BASE_URL", "http://10.0.0.1:18766")
    monkeypatch.delenv("FLEET_BEARER_TOKEN", raising=False)
    argv = ["docker", "run", "img"]
    out = runner._inject_host_metrics_client_env_for_docker_run(
        runner._inject_fleet_job_id_for_docker_run(argv, "x")
    )
    assert any("FLEET_HOST_METRICS_URL=" in a for a in out)
    assert not any(str(a).startswith("FLEET_HOST_METRICS_TOKEN=") for a in out)


def test_inject_host_metrics_off_matches_job_id_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER", raising=False)
    monkeypatch.setenv("FLEET_HOST_METRICS_BASE_URL", "http://should-not-apply")
    argv = ["docker", "run", "--rm", "img", "true"]
    job_only = runner._inject_fleet_job_id_for_docker_run(argv, "abc123")
    out = runner._inject_host_metrics_client_env_for_docker_run(job_only)
    assert out == job_only
    assert not any("FLEET_HOST_METRICS" in str(a) for a in out)


def test_inject_host_metrics_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER", "true")
    monkeypatch.delenv("FLEET_HOST_METRICS_BASE_URL", raising=False)
    argv = ["docker", "run", "img"]
    job_only = runner._inject_fleet_job_id_for_docker_run(argv, "z")
    out = runner._inject_host_metrics_client_env_for_docker_run(job_only)
    assert out == job_only
