"""forge-2b-poc through the generic managed-service rollout API (no SSH): registry wiring + script contract.

The script is exercised with a stub ``docker`` on PATH so the Fleet step/status protocol, the DCE-mode validation,
the sticky mode file and the healthz/dce_mode parity gate are tested without containers.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from fleet_server import rollout_registry

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rollout-forge-2b-poc.sh"

_DOCKER_STUB = """#!/usr/bin/env bash
# minimal docker stand-in: records calls, answers network/inspect/exec/compose
echo "docker $*" >> "$DOCKER_STUB_LOG"
case "$1" in
  network) exit 0 ;;
  inspect) echo healthy ;;
  exec) if [[ "${STUB_LIVE_MODE:-off}" == absent ]]; then echo '{"ok": true, "service": "forge-2b-poc"}'; else printf '{"ok": true, "service": "forge-2b-poc", "dce_mode": "%s"}\\n' "${STUB_LIVE_MODE:-off}"; fi ;;
  compose) exit 0 ;;
  logs) exit 0 ;;
esac
exit 0
"""


def test_registry_exposes_forge_2b_poc_with_dce_mode_override() -> None:
    spec = rollout_registry.get("forge-2b-poc")
    assert spec is not None and spec.script == "scripts/rollout-forge-2b-poc.sh"
    assert spec.supports_source_overlay is False, "git is the only code carrier for the shim (vendor/ is synced + pushed)"
    assert spec.overrides["forge_2b_dce_mode"] == "FORGE_2B_DCE_MODE" and spec.overrides["dce_mode"] == "FORGE_2B_DCE_MODE"
    assert spec.overrides["forge_2b_skip_build"] == "FORGE_2B_SKIP_BUILD"
    env: dict[str, str] = {}
    unknown = rollout_registry.apply_overrides(env, spec, {"forge_2b_dce_mode": "shadow", "bogus": "1"})
    assert env["FORGE_2B_DCE_MODE"] == "shadow" and unknown == ["bogus"]
    assert SCRIPT.is_file() and SCRIPT.stat().st_mode & stat.S_IXUSR
    assert "fleet-rollout-step.sh" in SCRIPT.read_text(encoding="utf-8")


def _run(tmp_path: Path, *, mode: str | None, live_mode: str = "off", with_dce_pkg: bool = True, extra_env: dict | None = None):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    stub = fake_bin / "docker"
    stub.write_text(_DOCKER_STUB, encoding="utf-8")
    stub.chmod(0o755)
    deploy = tmp_path / "fleet" / "deploy" / "forge-2b-poc" / "vendor" / "forge_2b"
    deploy.mkdir(parents=True, exist_ok=True)
    (deploy / "facade.py").write_text("# stub\n", encoding="utf-8")
    if with_dce_pkg:
        (deploy / "dce").mkdir(exist_ok=True)
    elif (deploy / "dce").is_dir():
        (deploy / "dce").rmdir()
    (deploy.parent / "SOURCES.txt").write_text("forge-2b test\n", encoding="utf-8")
    (tmp_path / "fleet" / "deploy" / "forge-2b-poc" / "compose.yaml").write_text("name: x\n", encoding="utf-8")
    scripts = tmp_path / "fleet" / "scripts"
    scripts.mkdir(exist_ok=True)
    for name in ("rollout-forge-2b-poc.sh", "fleet-rollout-step.sh"):
        (scripts / name).write_text((ROOT / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")
        (scripts / name).chmod(0o755)
    env_file = tmp_path / "forge-2b.env"
    env_file.write_text("FORGE_2B_API_KEY=test\n", encoding="utf-8")
    log = tmp_path / "rollout.log"
    status_dir = tmp_path / "status"
    (tmp_path / "docker.log").unlink(missing_ok=True)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "DOCKER_STUB_LOG": str(tmp_path / "docker.log"),
        "STUB_LIVE_MODE": live_mode,
        "FORGE_2B_ENV_FILE": str(env_file),
        "FORGE_2B_DCE_MODE_FILE": str(tmp_path / "dce-mode"),
        "FLEET_FORGE_2B_ROLLOUT_LOG": str(log),
        "FLEET_ROLLOUT_STATUS_DIR": str(status_dir),
        **(extra_env or {}),
    }
    env.pop("FORGE_2B_DCE_MODE", None)
    if mode is not None:
        env["FORGE_2B_DCE_MODE"] = mode
    r = subprocess.run(["bash", str(scripts / "rollout-forge-2b-poc.sh")], env=env, capture_output=True, text=True, timeout=60, check=False)
    status = json.loads((status_dir / "forge-2b-poc.json").read_text(encoding="utf-8")) if (status_dir / "forge-2b-poc.json").exists() else {}
    docker_log = (tmp_path / "docker.log").read_text(encoding="utf-8") if (tmp_path / "docker.log").exists() else ""
    return r, status, docker_log


def test_script_applies_mode_records_it_and_reports_steps(tmp_path: Path) -> None:
    r, status, docker_log = _run(tmp_path, mode="shadow", live_mode="shadow")
    assert r.returncode == 0, r.stdout + r.stderr
    assert status["maintenance"] is False and status["failed"] is False and status["current_step"] == "done"
    assert {"prepare", "build", "restart", "health_check", "finalize"} <= set(status["steps_done"])
    assert "compose -f" in docker_log and "build --pull" in docker_log and "up -d --force-recreate" in docker_log
    assert (tmp_path / "dce-mode").read_text(encoding="utf-8").strip() == "shadow"
    assert "dce_mode=shadow" in r.stdout
    # sticky: a rollout without an explicit mode reuses the recorded one; skip_build skips the build step
    r, status, docker_log = _run(tmp_path, mode=None, live_mode="shadow", extra_env={"FORGE_2B_SKIP_BUILD": "1"})
    assert r.returncode == 0 and "dce_mode=shadow" in r.stdout and "build --pull" not in docker_log
    assert "build" not in status["steps_done"]


def test_script_refuses_bad_mode_and_mode_without_dce_package_and_mismatched_container(tmp_path: Path) -> None:
    r, status, docker_log = _run(tmp_path, mode="maybe")
    assert r.returncode == 2 and "must be off|shadow|on" in r.stderr and docker_log == ""
    r, status, _ = _run(tmp_path, mode="on", with_dce_pkg=False)
    assert r.returncode == 2 and status["failed"] is True and status["failed_step"] == "prepare" and "no dce/ package" in status["error"]
    # the container must report the mode the rollout asked for; otherwise the rollout fails and the mode file is not written
    r, status, _ = _run(tmp_path, mode="shadow", live_mode="off")
    assert r.returncode == 1 and status["failed"] is True and status["failed_step"] == "health_check" and "dce_mode=off" in status["error"]
    assert not (tmp_path / "dce-mode").exists()
    # off against a pre-DCE image (no dce_mode field in /healthz) is accepted: that is today's production behaviour
    r, status, _ = _run(tmp_path, mode="off", live_mode="absent", with_dce_pkg=False)
    assert r.returncode == 0 and status["failed"] is False
