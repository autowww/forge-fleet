"""Admin-triggered Forge Market Studio compose rollout on the Fleet host."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import rollout_slot, rollout_status
from fleet_server.market_studio_rollout_env import rollout_identity

_ROLLOUT_ENV_KEYS = (
    "FORGE_MARKET_ROOT",
    "FORGE_MARKET_STUDIO_ROOT",
    "FORGE_MARKET_COMPOSE_FILES",
    "FORGE_MARKET_STUDIO_HOST_PORT",
    "FORGE_MARKET_DOCKERFILE",
    "FORGE_MARKET_GIT_REF",
    "FORGE_MARKET_GIT_FALLBACK_ROOT",
    "FORGE_MARKET_DOCKER_BUILD_NO_CACHE",
    "FORGE_MARKET_SEC_CONTACT",
    "FORGE_MARKET_RUN_SCHEMA_MIGRATE",
    "FORGE_MARKET_ENV",
    "FORGE_MARKET_SKIP_BUILD",
    "FORGE_MARKET_APP_IMAGE",
    "FORGE_MARKET_GIT_SHA",
    "FORGE_MARKET_PURGE_SYMBOLS",
    "FORGE_MARKET_CONFIRM_COVERAGE_V2_DROP",
    "FORGE_MARKET_CONFIRM_BARS_V2_DROP",
    "FORGE_MARKET_CONFIRM_OBS_DICTIONARY",
    "FORGE_MARKET_JOB_DRAIN_MODE",
    "FORGE_MARKET_PAUSE_SCHEDULER",
    "FORGE_MARKET_JOB_PAUSE_TIMEOUT_SEC",
    "FORGE_MARKET_JOB_DRAIN_TIMEOUT_SEC",
    "FORGE_MARKET_SKIP_GIT_SYNC",
    "FORGE_MARKET_GIT_HARD_RESET",
)


def _fleet_user_env_file() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "forge-fleet" / "forge-fleet.env"


def _merge_env_file(env: dict[str, str], path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key and key not in env:
            env[key] = val


def _rollout_env(overrides: dict[str, Any] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    _merge_env_file(env, _fleet_user_env_file())
    if overrides:
        _apply_rollout_overrides(env, overrides)
    return env


def _apply_rollout_overrides(env: dict[str, str], overrides: dict[str, Any]) -> None:
    alias = {
        "forge_market_root": "FORGE_MARKET_ROOT",
        "forge_market_studio_root": "FORGE_MARKET_STUDIO_ROOT",
        "forge_market_compose_files": "FORGE_MARKET_COMPOSE_FILES",
        "forge_market_studio_host_port": "FORGE_MARKET_STUDIO_HOST_PORT",
        "forge_market_dockerfile": "FORGE_MARKET_DOCKERFILE",
        "forge_market_git_ref": "FORGE_MARKET_GIT_REF",
        "forge_market_git_fallback_root": "FORGE_MARKET_GIT_FALLBACK_ROOT",
        "forge_market_docker_build_no_cache": "FORGE_MARKET_DOCKER_BUILD_NO_CACHE",
        "forge_market_sec_contact": "FORGE_MARKET_SEC_CONTACT",
        "forge_market_run_schema_migrate": "FORGE_MARKET_RUN_SCHEMA_MIGRATE",
        "run_schema_migrate": "FORGE_MARKET_RUN_SCHEMA_MIGRATE",
        "forge_market_env": "FORGE_MARKET_ENV",
        "forge_market_skip_build": "FORGE_MARKET_SKIP_BUILD",
        "forge_market_app_image": "FORGE_MARKET_APP_IMAGE",
        "forge_market_git_sha": "FORGE_MARKET_GIT_SHA",
        "forge_market_purge_symbols": "FORGE_MARKET_PURGE_SYMBOLS",
        "forge_market_confirm_coverage_v2_drop": "FORGE_MARKET_CONFIRM_COVERAGE_V2_DROP",
        "forge_market_confirm_bars_v2_drop": "FORGE_MARKET_CONFIRM_BARS_V2_DROP",
        "forge_market_confirm_obs_dictionary": "FORGE_MARKET_CONFIRM_OBS_DICTIONARY",
        "forge_market_job_drain_mode": "FORGE_MARKET_JOB_DRAIN_MODE",
        "forge_market_pause_scheduler": "FORGE_MARKET_PAUSE_SCHEDULER",
        "forge_market_job_pause_timeout_sec": "FORGE_MARKET_JOB_PAUSE_TIMEOUT_SEC",
        "forge_market_job_drain_timeout_sec": "FORGE_MARKET_JOB_DRAIN_TIMEOUT_SEC",
        "forge_market_skip_git_sync": "FORGE_MARKET_SKIP_GIT_SYNC",
        "forge_market_git_hard_reset": "FORGE_MARKET_GIT_HARD_RESET",
    }
    for src, dst in alias.items():
        raw = overrides.get(src)
        if raw is None:
            raw = overrides.get(dst)
        if raw is None:
            continue
        if dst == "FORGE_MARKET_RUN_SCHEMA_MIGRATE":
            if isinstance(raw, bool):
                env[dst] = "1" if raw else "0"
            else:
                val = str(raw).strip()
                if val.lower() in ("1", "true", "yes", "on"):
                    env[dst] = "1"
                elif val.lower() in ("0", "false", "no", "off"):
                    env[dst] = "0"
                elif val:
                    env[dst] = val
            continue
        if dst in {
            "FORGE_MARKET_PAUSE_SCHEDULER",
            "FORGE_MARKET_SKIP_BUILD",
            "FORGE_MARKET_SKIP_GIT_SYNC",
            "FORGE_MARKET_GIT_HARD_RESET",
        }:
            if isinstance(raw, bool):
                env[dst] = "1" if raw else "0"
            else:
                val = str(raw).strip().lower()
                if val in ("1", "true", "yes", "on"):
                    env[dst] = "1"
                elif val in ("0", "false", "no", "off"):
                    env[dst] = "0"
                elif val:
                    env[dst] = str(raw).strip()
            continue
        val = str(raw).strip()
        if val:
            env[dst] = val


def _rollout_service_id(env: dict[str, str]) -> str:
    sid, _ = rollout_identity(env.get("FORGE_MARKET_ENV", "prod"))
    return sid


def rollout_log_path(*, env: dict[str, str] | None = None) -> Path:
    env = env or _rollout_env()
    raw = str(env.get("FLEET_FORGE_MARKET_STUDIO_ROLLOUT_LOG", "") or "").strip()
    if raw:
        return Path(raw)
    sid = _rollout_service_id(env)
    return rollout_status.LOG_DIR / f"{sid}.log"


def _log_tail(log_path: Path, *, lines: int = 80) -> str:
    if not log_path.is_file():
        return ""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    parts = text.splitlines()
    return "\n".join(parts[-lines:])


def _record_rollout_failure(
    env: dict[str, str],
    log_path: Path,
    *,
    failed_step: str,
    error: str,
) -> dict[str, Any]:
    sid = _rollout_service_id(env)
    status_path = rollout_status.STATUS_DIR / f"{sid}.json"
    if status_path.is_file():
        try:
            existing = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing.get("failed"):
                return rollout_status.read_rollout_status(sid)
        except (OSError, json.JSONDecodeError):
            pass
    rollout_status.write_rollout_failure(
        sid,
        failed_step=failed_step,
        error=error,
        log_tail=_log_tail(log_path),
    )
    return rollout_status.read_rollout_status(sid)


def read_rollout_log(*, max_bytes: int = 16000) -> dict[str, Any]:
    p = rollout_log_path()
    if not p.is_file():
        return {"ok": True, "log_path": str(p), "log": "", "exists": False}
    data = p.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return {
        "ok": True,
        "log_path": str(p),
        "exists": True,
        "log": data.decode("utf-8", errors="replace"),
    }


def _rollout_script(repo_root: Path) -> Path:
    p = repo_root / "scripts" / "rollout-forge-market-studio.sh"
    if not p.is_file():
        raise FileNotFoundError("rollout_script_missing")
    return p


def schedule_rollout(repo_root: Path, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    env = _rollout_env(overrides)
    log_path = rollout_log_path(env=env)
    service_id = _rollout_service_id(env)
    env_id = rollout_slot.normalize_env_id(env.get("FORGE_MARKET_ENV", "prod"))
    holder = rollout_slot.new_legacy_holder()
    acquired = rollout_slot.try_acquire(
        service_id,
        holder,
        environment=env_id,
        holder_kind="legacy",
    )
    if not acquired.get("ok"):
        return acquired
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        time.sleep(0.5)
        rc = 1
        try:
            try:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n--- rollout {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n")
                    fh.flush()
                    r = subprocess.run(
                        ["bash", str(script)],
                        cwd=str(repo_root),
                        env=env,
                        stdout=fh,
                        stderr=subprocess.STDOUT,
                        timeout=int(env.get("FLEET_FORGE_MARKET_STUDIO_ROLLOUT_TIMEOUT_SEC", "1800")),
                        stdin=subprocess.DEVNULL,
                        check=False,
                    )
                    rc = int(r.returncode)
            except subprocess.TimeoutExpired as exc:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"rollout failed: timeout after {exc.timeout}s\n")
                _record_rollout_failure(
                    env,
                    log_path,
                    failed_step="timeout",
                    error=f"rollout_timeout after {exc.timeout}s",
                )
                return
            except (OSError, subprocess.SubprocessError) as exc:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"rollout failed: {exc}\n")
                _record_rollout_failure(
                    env,
                    log_path,
                    failed_step="launcher",
                    error=str(exc)[:800],
                )
                return
            if rc != 0:
                _record_rollout_failure(
                    env,
                    log_path,
                    failed_step="rollout_script",
                    error=f"rollout script exited with code {rc}",
                )
        finally:
            rollout_slot.release(service_id, holder)

    threading.Thread(target=_run, daemon=True).start()
    return {
        "ok": True,
        "scheduled": True,
        "service_id": service_id,
        "script": str(script),
        "log_path": str(log_path),
        "overrides": {k: env.get(k) for k in _ROLLOUT_ENV_KEYS if env.get(k)},
        "note": (
            "Rollout runs in background; poll "
            f"GET /v1/managed-services/{service_id}/maintenance-status for progress and failures."
        ),
    }


def run_rollout_sync(repo_root: Path, *, timeout_sec: int = 1800, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    env = _rollout_env(overrides)
    log_path = rollout_log_path(env=env)
    service_id = _rollout_service_id(env)
    env_id = rollout_slot.normalize_env_id(env.get("FORGE_MARKET_ENV", "prod"))
    holder = rollout_slot.new_legacy_holder()
    acquired = rollout_slot.try_acquire(
        service_id,
        holder,
        environment=env_id,
        holder_kind="legacy",
    )
    if not acquired.get("ok"):
        return acquired
    try:
        try:
            r = subprocess.run(
                ["bash", str(script)],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"rollout failed: timeout after {exc.timeout}s\n")
            status = _record_rollout_failure(
                env,
                log_path,
                failed_step="timeout",
                error=f"rollout_timeout after {exc.timeout}s",
            )
            return {
                "ok": False,
                "error": "rollout_timeout",
                "timeout_sec": timeout_sec,
                "service_id": service_id,
                "maintenance_status": status,
            }
        out: dict[str, Any] = {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "stdout": (r.stdout or "")[-16000:],
            "stderr": (r.stderr or "")[-8000:],
            "overrides": {k: env.get(k) for k in _ROLLOUT_ENV_KEYS if env.get(k)},
            "service_id": service_id,
            "log_path": str(log_path),
        }
        if r.returncode != 0:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"rollout failed: script exit {r.returncode}\n")
                if r.stdout:
                    fh.write(r.stdout[-4000:])
                if r.stderr:
                    fh.write(r.stderr[-4000:])
            out["maintenance_status"] = _record_rollout_failure(
                env,
                log_path,
                failed_step="rollout_script",
                error=f"rollout script exited with code {r.returncode}",
            )
        else:
            out["maintenance_status"] = rollout_status.read_rollout_status(service_id)
        return out
    finally:
        rollout_slot.release(service_id, holder)
