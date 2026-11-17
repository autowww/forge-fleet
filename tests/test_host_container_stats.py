"""Tests for host_container_stats."""

from __future__ import annotations

from unittest.mock import patch

from fleet_server import environment_stats, host_container_stats


def test_container_stats_payload_docker_ps_failure():
    with patch(
        "fleet_server.host_container_stats._running_container_names",
        return_value=([], "boom"),
    ):
        out = host_container_stats.container_stats_payload(use_cache=False)
    assert out["ok"] is False
    assert out["containers"] == []
    assert out["docker_ps_error"] == "boom"


def test_container_stats_payload_truncates_and_sorts():
    names = [f"c{i}" for i in range(90)]
    stats = {
        f"c{i}": {
            "container_name": f"c{i}",
            "cpu_pct": float(i),
            "mem_pct": 1.0,
            "mem_usage_bytes": 1,
            "mem_limit_bytes": 2,
            "pids": 1,
            "state": "running",
        }
        for i in range(80)
    }
    with patch(
        "fleet_server.host_container_stats._running_container_names",
        return_value=(names, None),
    ):
        with patch("fleet_server.host_container_stats.environment_stats.docker_stats_map", return_value=stats):
            out = host_container_stats.container_stats_payload(use_cache=False)
    assert out["ok"] is True
    assert out["truncated"] is True
    assert out["containers_total_reported"] == 90
    assert len(out["containers"]) == 80
    assert out["containers"][0]["cpu_pct"] == 79.0


def test_docker_stats_map_nonzero_exit_returns_empty():
    with patch("subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        out = environment_stats.docker_stats_map(["x"])
    assert out == {}