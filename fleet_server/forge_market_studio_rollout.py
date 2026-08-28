"""Admin-triggered Forge Market Studio compose rollout on the Fleet host."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

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
    }
    for src, dst in alias.items():
        val = str(overrides.get(src) or overrides.get(dst) or "").strip()
        if val:
            env[dst] = val


def rollout_log_path() -> Path:
    env = _rollout_env()
    raw = str(env.get("FLEET_FORGE_MARKET_STUDIO_ROLLOUT_LOG", "") or "").strip()
    return Path(raw) if raw else Path.home() / ".local/state/forge-fleet" / "forge-market-studio-rollout.log"


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
    log_path = rollout_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        time.sleep(0.5)
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n--- rollout {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n")
                fh.flush()
                subprocess.run(
                    ["bash", str(script)],
                    cwd=str(repo_root),
                    env=env,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    timeout=int(env.get("FLEET_FORGE_MARKET_STUDIO_ROLLOUT_TIMEOUT_SEC", "1800")),
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"rollout failed: {exc}\n")

    threading.Thread(target=_run, daemon=True).start()
    return {
        "ok": True,
        "scheduled": True,
        "script": str(script),
        "log_path": str(log_path),
        "overrides": {k: env.get(k) for k in _ROLLOUT_ENV_KEYS if env.get(k)},
        "note": "Rollout runs in background; poll GET /v1/admin/forge-market-studio-rollout-log for progress.",
    }


def run_rollout_sync(repo_root: Path, *, timeout_sec: int = 1800, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    env = _rollout_env(overrides)
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
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "rollout_timeout", "timeout_sec": timeout_sec}
    return {
        "ok": r.returncode == 0,
        "returncode": r.returncode,
        "stdout": (r.stdout or "")[-16000:],
        "stderr": (r.stderr or "")[-8000:],
        "overrides": {k: env.get(k) for k in _ROLLOUT_ENV_KEYS if env.get(k)},
    }
