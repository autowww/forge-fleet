"""Admin-triggered pattern cell rollup backfill for Market Studio Postgres."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import forge_market_studio_rollout as fmsr
from fleet_server import rollout_slot, rollout_status

_BACKFILL_ENV_KEYS = (
    "FORGE_MARKET_ENV",
    "FORGE_MARKET_ROOT",
    "FORGE_MARKET_COMPOSE_FILES",
    "FORGE_MARKET_PATTERN_ROLLUPS_TICKERS",
    "FORGE_MARKET_PATTERN_ROLLUPS_INTERVALS",
    "FORGE_MARKET_PATTERN_ROLLUPS_LIMIT",
    "FORGE_MARKET_PATTERN_ROLLUPS_CHECKPOINT",
    "FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN",
)

_BODY_ALIASES: dict[str, str] = {
    "forge_market_env": "FORGE_MARKET_ENV",
    "forge_market_root": "FORGE_MARKET_ROOT",
    "forge_market_compose_files": "FORGE_MARKET_COMPOSE_FILES",
    "tickers": "FORGE_MARKET_PATTERN_ROLLUPS_TICKERS",
    "intervals": "FORGE_MARKET_PATTERN_ROLLUPS_INTERVALS",
    "limit": "FORGE_MARKET_PATTERN_ROLLUPS_LIMIT",
    "checkpoint": "FORGE_MARKET_PATTERN_ROLLUPS_CHECKPOINT",
    "dry_run": "FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN",
}


def _backfill_env(overrides: dict[str, Any] | None = None) -> dict[str, str]:
    env = fmsr._rollout_env(overrides)
    if not overrides:
        return env
    for src, dst in _BODY_ALIASES.items():
        raw = overrides.get(src)
        if raw is None:
            raw = overrides.get(dst)
        if raw is None:
            continue
        if dst == "FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN":
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
        if dst == "FORGE_MARKET_PATTERN_ROLLUPS_LIMIT":
            try:
                env[dst] = str(max(0, int(raw)))
            except (TypeError, ValueError):
                continue
            continue
        val = str(raw).strip()
        if val:
            env[dst] = val
    return env


def _service_id(env: dict[str, str]) -> str:
    return fmsr._rollout_service_id(env)


def backfill_log_path(*, env: dict[str, str] | None = None) -> Path:
    env = env or _backfill_env()
    raw = str(env.get("FLEET_FORGE_MARKET_PATTERN_ROLLUPS_BACKFILL_LOG", "") or "").strip()
    if raw:
        return Path(raw)
    sid = _service_id(env)
    return rollout_status.LOG_DIR / f"{sid}-pattern-rollups-backfill.log"


def read_backfill_log(*, max_bytes: int = 16000, env: dict[str, str] | None = None) -> dict[str, Any]:
    p = backfill_log_path(env=env)
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


def _backfill_script(repo_root: Path) -> Path:
    p = repo_root / "scripts" / "backfill-forge-market-pattern-rollups.sh"
    if not p.is_file():
        raise FileNotFoundError("backfill_script_missing")
    return p


def _timeout_sec(env: dict[str, str]) -> int:
    raw = str(env.get("FLEET_FORGE_MARKET_PATTERN_ROLLUPS_BACKFILL_TIMEOUT_SEC", "") or "").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 86400


def schedule_backfill(repo_root: Path, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    script = _backfill_script(repo_root)
    env = _backfill_env(overrides)
    log_path = backfill_log_path(env=env)
    service_id = _service_id(env)
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
                    fh.write(
                        f"\n--- pattern rollups backfill {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n"
                    )
                    fh.flush()
                    r = subprocess.run(
                        ["bash", str(script)],
                        cwd=str(repo_root),
                        env=env,
                        stdout=fh,
                        stderr=subprocess.STDOUT,
                        timeout=_timeout_sec(env),
                        stdin=subprocess.DEVNULL,
                        check=False,
                    )
                    rc = int(r.returncode)
            except subprocess.TimeoutExpired as exc:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"backfill failed: timeout after {exc.timeout}s\n")
                return
            except (OSError, subprocess.SubprocessError) as exc:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"backfill failed: {exc}\n")
                return
            if rc != 0:
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(f"backfill script exited with code {rc}\n")
        finally:
            rollout_slot.release(service_id, holder)

    threading.Thread(target=_run, daemon=True).start()
    return {
        "ok": True,
        "scheduled": True,
        "service_id": service_id,
        "script": str(script),
        "log_path": str(log_path),
        "overrides": {k: env.get(k) for k in _BACKFILL_ENV_KEYS if env.get(k)},
        "note": (
            "Backfill runs in background; poll "
            f"GET /v1/admin/forge-market-pattern-rollups-backfill-log or "
            f"GET /v1/managed-services/{service_id}/maintenance-status."
        ),
    }


def run_backfill_sync(
    repo_root: Path,
    *,
    timeout_sec: int | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    script = _backfill_script(repo_root)
    env = _backfill_env(overrides)
    log_path = backfill_log_path(env=env)
    service_id = _service_id(env)
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
    timeout = timeout_sec if timeout_sec is not None else _timeout_sec(env)
    try:
        try:
            r = subprocess.run(
                ["bash", str(script)],
                cwd=str(repo_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "backfill_timeout", "timeout_sec": timeout}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- pattern rollups backfill sync ---\n")
            if r.stdout:
                fh.write(r.stdout)
            if r.stderr:
                fh.write(r.stderr)
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "service_id": service_id,
            "log_path": str(log_path),
            "stdout": (r.stdout or "")[-16000:],
            "stderr": (r.stderr or "")[-8000:],
        }
    finally:
        rollout_slot.release(service_id, holder)
