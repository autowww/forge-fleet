"""Generic managed-service rollout scheduler."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import rollout_registry, rollout_slot, rollout_status


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _rollout_env(spec: rollout_registry.RolloutSpec, body: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    env = os.environ.copy()
    env_path = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "forge-fleet" / "forge-fleet.env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in env:
                env[key] = val
    if spec.default_env:
        env.setdefault("FORGE_MARKET_ENV", spec.default_env)
    unknown = rollout_registry.apply_overrides(env, spec, body)
    return env, unknown


def _script_path(spec: rollout_registry.RolloutSpec) -> Path:
    p = _repo_root() / spec.script
    if not p.is_file():
        raise FileNotFoundError(f"rollout_script_missing: {spec.script}")
    return p


def _log_path(service_id: str) -> Path:
    return rollout_status.LOG_DIR / f"{service_id}.log"


def schedule_rollout(service_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = rollout_registry.get(service_id)
    if spec is None:
        return {"ok": False, "error": "unknown_service", "service_id": service_id}
    body = dict(body or {})
    env, unknown = _rollout_env(spec, body)
    if unknown:
        return {
            "ok": False,
            "error": "unknown_rollout_keys",
            "unknown_keys": sorted(unknown),
            "allowed_keys": sorted(set(spec.overrides.keys()) | {"sync"}),
        }
    slot_id = rollout_registry.resolve_slot_service_id(spec, body)
    env_id = rollout_slot.normalize_env_id(str(body.get(spec.slot_env_param or "") or spec.default_env or ""))
    holder = rollout_slot.new_legacy_holder()
    acquired = rollout_slot.try_acquire(
        slot_id,
        holder,
        environment=env_id or None,
        holder_kind="legacy",
    )
    if not acquired.get("ok"):
        return acquired
    script = _script_path(spec)
    log_path = _log_path(slot_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        time.sleep(0.5)
        rc = 1
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n--- rollout {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n")
                fh.flush()
                r = subprocess.run(
                    ["bash", str(script)],
                    cwd=str(_repo_root()),
                    env=env,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    timeout=int(env.get("FLEET_ROLLOUT_TIMEOUT_SEC", "1800")),
                    stdin=subprocess.DEVNULL,
                    check=False,
                )
                rc = int(r.returncode)
        except subprocess.TimeoutExpired as exc:
            rollout_status.write_rollout_failure(
                slot_id,
                failed_step="timeout",
                error=f"rollout_timeout after {exc.timeout}s",
            )
            rollout_slot.release(slot_id, holder)
            return
        except (OSError, subprocess.SubprocessError) as exc:
            rollout_status.write_rollout_failure(
                slot_id,
                failed_step="launcher",
                error=str(exc)[:800],
            )
            rollout_slot.release(slot_id, holder)
            return
        if rc != 0:
            rollout_status.write_rollout_failure(
                slot_id,
                failed_step="rollout_script",
                error=f"rollout script exited with code {rc}",
            )
        rollout_slot.release(slot_id, holder)

    if str(body.get("sync") or "").strip().lower() in ("1", "true", "yes"):
        _run()
        status = rollout_status.read_rollout_status(slot_id)
        return {"ok": not status.get("failed"), "sync": True, "service_id": slot_id, **status}

    threading.Thread(target=_run, daemon=True, name=f"rollout-{slot_id}").start()
    return {
        "ok": True,
        "scheduled": True,
        "service_id": slot_id,
        "script": str(script),
        "log_path": str(log_path),
        "note": "Rollout runs in background; poll GET /v1/managed-services/{service_id}/maintenance-status",
    }


def run_rollout_sync(service_id: str, body: dict[str, Any] | None = None, *, timeout_sec: int = 1800) -> dict[str, Any]:
    payload = dict(body or {})
    payload["sync"] = True
    if timeout_sec:
        os.environ.setdefault("FLEET_ROLLOUT_TIMEOUT_SEC", str(timeout_sec))
    return schedule_rollout(service_id, payload)
