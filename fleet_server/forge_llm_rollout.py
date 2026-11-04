"""Admin-triggered forge-llm control-plane rollout on the Fleet host."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


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


RUNNER_APPLY_MODES = frozenset({"observe", "apply"})


def _rollout_env(*, runner_apply: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    _merge_env_file(env, _fleet_user_env_file())
    if runner_apply:
        mode = str(runner_apply).strip().lower()
        if mode not in RUNNER_APPLY_MODES:
            raise ValueError("invalid_runner_apply")
        # ``apply`` lets scripts/apply-runner-host.sh write the Ollama drop-in and pull
        # missing ``models`` from runner.granite.yaml (catalog pins) during this rollout.
        env["FORGE_LLM_RUNNER_APPLY"] = mode
    return env


def rollout_log_path() -> Path:
    env = _rollout_env()
    raw = str(env.get("FLEET_FORGE_LLM_ROLLOUT_LOG", "") or "").strip()
    return Path(raw) if raw else Path.home() / ".local/state/forge-fleet" / "forge-llm-rollout.log"


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
    p = repo_root / "scripts" / "rollout-forge-llm-control-plane.sh"
    if not p.is_file():
        raise FileNotFoundError("rollout_script_missing")
    return p


def schedule_rollout(repo_root: Path, *, runner_apply: str | None = None) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    env = _rollout_env(runner_apply=runner_apply)
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
                    timeout=int(env.get("FLEET_FORGE_LLM_ROLLOUT_TIMEOUT_SEC", "1800")),
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
        "runner_apply": env.get("FORGE_LLM_RUNNER_APPLY", "observe"),
        "note": "Rollout runs in background; poll GET /v1/admin/forge-llm-rollout-log for progress.",
    }


def run_rollout_sync(
    repo_root: Path,
    *,
    timeout_sec: int = 1800,
    runner_apply: str | None = None,
) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    env = _rollout_env(runner_apply=runner_apply)
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
    }
