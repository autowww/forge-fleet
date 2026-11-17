"""Schedule a host-side forge-lcdl GPU image build. The script git-fetches, then docker build."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import repo_root as fleet_roots

_LOG_NAME = "lcdl-nn-gpu-worker.log"


def _script(repo_root: Path) -> tuple[Path, Path]:
    root, script = fleet_roots.resolve_rollout_script(
        fleet_roots.LCDL_GPU_WORKER_BUILD_SCRIPT,
        runtime=repo_root,
    )
    return root, script


def log_path() -> Path:
    raw = str(os.environ.get("FLEET_LCDL_GPU_WORKER_BUILD_LOG") or "").strip()
    if raw:
        return Path(raw)
    return Path.home() / ".local" / "state" / "forge-fleet" / "rollout-logs" / _LOG_NAME


def schedule_build(repo_root: Path, *, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    root, script = _script(repo_root)
    if not script.is_file():
        raise FileNotFoundError(str(script))
    env = os.environ.copy()
    for key, env_name in (
        ("forge_lcdl_root", "FORGE_LCDL_ROOT"),
        ("forge_lcdl_git_ref", "FORGE_LCDL_GIT_REF"),
        ("forge_lcdl_nn_gpu_image", "FORGE_LCDL_NN_GPU_IMAGE"),
    ):
        if overrides and overrides.get(key):
            env[env_name] = str(overrides[key]).strip()
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    def _run() -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n--- build {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ---\n")
            handle.flush()
            subprocess.run(
                ["bash", str(script)],
                cwd=str(root),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=int(env.get("FLEET_LCDL_GPU_WORKER_BUILD_TIMEOUT_SEC", "3600")),
                stdin=subprocess.DEVNULL,
                check=False,
            )

    threading.Thread(target=_run, name="lcdl-gpu-worker-build", daemon=True).start()
    return {"ok": True, "scheduled": True, "script": str(script), "log_path": str(path)}
