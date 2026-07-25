"""Admin-triggered forge-llm control-plane rollout on the Fleet host."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def _rollout_script(repo_root: Path) -> Path:
    p = repo_root / "scripts" / "rollout-forge-llm-control-plane.sh"
    if not p.is_file():
        raise FileNotFoundError("rollout_script_missing")
    return p


def schedule_rollout(repo_root: Path) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    env = os.environ.copy()
    log_path = Path(
        str(env.get("FLEET_FORGE_LLM_ROLLOUT_LOG", "") or "").strip()
        or (Path.home() / ".local/state/forge-fleet/forge-llm-rollout.log")
    )
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
        "note": "Rollout runs in background; tail log_path on the host for progress.",
    }


def run_rollout_sync(repo_root: Path, *, timeout_sec: int = 1800) -> dict[str, Any]:
    script = _rollout_script(repo_root)
    try:
        r = subprocess.run(
            ["bash", str(script)],
            cwd=str(repo_root),
            env=os.environ.copy(),
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
