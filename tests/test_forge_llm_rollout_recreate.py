"""Rollout must force-recreate the gateway when the runner YAML changed on disk.

Regression (P2B, 2026-11-04): ``compose.yaml`` bind-mounts ``configs/runner.granite.yaml`` as a
single file. ``git pull`` replaced it (new inode), the running container kept the old bytes, and
``docker compose up -d`` saw nothing to recreate. The rollout reported ``rollout complete`` while
``GET /v1/llm/catalog`` still showed the un-promoted pin. The fix compares host bytes with the
container's ``/config/runner.yaml`` and adds ``--force-recreate`` only when they differ.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rollout-forge-llm-control-plane.sh"


def _extract_function(body: str, name: str) -> str:
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"{name}()"):
            end = next(i for i in range(idx + 1, len(lines)) if lines[i] == "}")
            return "\n".join(lines[idx : end + 1])
    raise AssertionError(f"{name} not found in {SCRIPT}")


def _write_fake_docker(bindir: Path, *, running: str, live_yaml: str) -> None:
    """Fake ``docker``: ``inspect`` reports running state, ``exec … cat`` prints live YAML,
    ``compose …`` records its argv to $COMPOSE_LOG."""
    script = f"""#!/usr/bin/env bash
case "$1" in
  inspect) printf '%s\\n' '{running}' ;;
  exec) printf '%s' '{live_yaml}' ;;
  compose)
    shift
    if [[ "$1" == "version" ]]; then exit 0; fi
    printf '%s\\n' "$*" >> "$COMPOSE_LOG" ;;
  *) echo "unexpected docker argv: $*" >&2; exit 99 ;;
esac
"""
    p = bindir / "docker"
    p.write_text(script, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)


def _run_deploy(tmp_path: Path, *, host_yaml: str, live_yaml: str, running: str = "true") -> str:
    root = tmp_path / "forge-llm-control-plane"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "runner.granite.yaml").write_text(host_yaml, encoding="utf-8")
    (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _write_fake_docker(bindir, running=running, live_yaml=live_yaml)
    compose_log = tmp_path / "compose.log"
    body = SCRIPT.read_text(encoding="utf-8")
    harness = "\n".join(
        [
            "set -uo pipefail",
            'log() { printf "%s\\n" "$*"; }',
            f'FORGE_LLM_ROOT="{root}"',
            'OLLAMA_FORWARDER_URL="http://host.docker.internal:11436"',
            _extract_function(body, "compose"),
            _extract_function(body, "_runner_yaml_changed_in_container"),
            _extract_function(body, "deploy_gateway_stack"),
            "deploy_gateway_stack",
        ]
    )
    r = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bindir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "COMPOSE_LOG": str(compose_log),
        },
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return compose_log.read_text(encoding="utf-8") if compose_log.exists() else ""


def test_force_recreate_when_runner_yaml_differs(tmp_path: Path) -> None:
    log = _run_deploy(tmp_path, host_yaml="artifact_pins: [promoted]\n", live_yaml="artifact_pins: []\n")
    up = [ln for ln in log.splitlines() if ln.startswith("-f compose.yaml up")]
    assert up == ["-f compose.yaml up -d --force-recreate forge-gateway"], log


def test_plain_up_when_runner_yaml_unchanged(tmp_path: Path) -> None:
    yaml = "artifact_pins: [same]\n"
    log = _run_deploy(tmp_path, host_yaml=yaml, live_yaml=yaml)
    up = [ln for ln in log.splitlines() if ln.startswith("-f compose.yaml up")]
    assert up == ["-f compose.yaml up -d forge-gateway"], log


def test_plain_up_when_no_running_container(tmp_path: Path) -> None:
    log = _run_deploy(tmp_path, host_yaml="a: 1\n", live_yaml="", running="false")
    up = [ln for ln in log.splitlines() if ln.startswith("-f compose.yaml up")]
    assert up == ["-f compose.yaml up -d forge-gateway"], log


@pytest.mark.skipif(os.name != "posix", reason="bash harness")
def test_build_always_precedes_up(tmp_path: Path) -> None:
    log = _run_deploy(tmp_path, host_yaml="a: 1\n", live_yaml="a: 2\n")
    lines = log.splitlines()
    assert lines[0] == "-f compose.yaml build forge-gateway"
    assert lines[1].startswith("-f compose.yaml up")
