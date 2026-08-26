"""Optional Docker BuildKit cache pruning for Fleet hosts."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any


def docker_builder_prune_hours() -> float:
    raw = str(os.environ.get("FLEET_DOCKER_BUILDER_PRUNE_HOURS") or "").strip()
    if not raw:
        return 168.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 168.0


def prune_docker_builder_cache(*, hours: float | None = None) -> dict[str, Any]:
    """Run ``docker builder prune`` for layers older than ``hours`` (0 = skip)."""
    prune_hours = docker_builder_prune_hours() if hours is None else max(0.0, hours)
    if prune_hours <= 0:
        return {"ok": True, "skipped": True, "reason": "disabled", "hours": prune_hours}
    if shutil.which("docker") is None:
        return {"ok": False, "skipped": True, "error": "docker_not_found", "hours": prune_hours}
    until = f"{int(prune_hours)}h"
    try:
        r = subprocess.run(
            ["docker", "builder", "prune", "-f", "--filter", f"until={until}"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "error": str(ex)[:800], "hours": prune_hours}
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    return {
        "ok": r.returncode == 0,
        "hours": prune_hours,
        "returncode": r.returncode,
        "stdout": out[:4000],
        "stderr": err[:2000],
    }
