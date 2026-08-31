"""Tests for environment_stats docker telemetry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import environment_stats, environments


def test_parse_mem_pair():
    used, limit, pct = environment_stats._parse_mem_pair("512MiB / 2GiB")
    assert used is not None
    assert limit is not None
    assert pct is not None
    assert pct > 0


def test_docker_stats_map_parses_json_lines():
    stdout = (
        '{"Name":"forge-market-postgres-dev","CPUPerc":"12.50%","MemUsage":"512MiB / 2GiB",'
        '"NetIO":"1kB / 2kB","BlockIO":"3kB / 4kB","PIDs":"17"}\n'
    )
    with patch("subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = stdout
        stats = environment_stats.docker_stats_map(["forge-market-postgres-dev"])
    assert "forge-market-postgres-dev" in stats
    row = stats["forge-market-postgres-dev"]
    assert row["cpu_pct"] == 12.5
    assert row["mem_pct"] is not None
    assert row["pids"] == 17


def test_environment_telemetry_snapshot(tmp_path: Path):
    rec = {
        "schema_version": 1,
        "id": "forge-market-studio--dev",
        "app_id": "forge-market-studio",
        "env_id": "dev",
        "template_id": "forge_market_studio",
        "compose_root": str(tmp_path / "compose"),
        "compose_files": ["compose.yaml"],
        "state": "ready",
        "ports": {"app": 19793, "postgres": 15433},
        "gateway_slug": "market-studio-dev",
    }
    environments.save_record(tmp_path, rec)
    compose_root = tmp_path / "compose"
    compose_root.mkdir(parents=True)
    (compose_root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    ps_rows = [
        {
            "Name": "forge-market-postgres-dev",
            "Service": "postgres",
            "State": "running",
        },
        {
            "Name": "forge-market-app-dev",
            "Service": "market-app",
            "State": "running",
        },
    ]
    with patch("fleet_server.managed_compose_service.compose_ps", return_value=(ps_rows, None)):
        with patch(
            "fleet_server.environment_stats.docker_stats_map",
            return_value={
                "forge-market-postgres-dev": {
                    "container_name": "forge-market-postgres-dev",
                    "cpu_pct": 9.5,
                    "mem_pct": 33.0,
                    "pids": 12,
                    "state": "running",
                }
            },
        ):
            rows = environment_stats.environment_telemetry_snapshot(tmp_path, use_cache=False)
    assert len(rows) == 1
    row = rows[0]
    assert row["env_id"] == "dev"
    assert row["containers_total"] == 2
    assert row["containers_running"] == 2
    assert row["postgres"]["cpu_pct"] == 9.5


def test_granite_postgres_flat():
    telemetry = [
        {
            "env_id": "dev",
            "postgres": {"container": "pg-dev", "cpu_pct": 5.0, "mem_pct": 10.0},
        }
    ]
    flat = environment_stats.granite_postgres_flat(telemetry)
    assert flat[0]["env_id"] == "dev"
    assert flat[0]["cpu_pct"] == 5.0
