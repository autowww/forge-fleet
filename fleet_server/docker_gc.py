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


def prune_docker_images_safe(
    *,
    hours: float = 168.0,
    prune_dangling: bool = True,
    prune_unused_all: bool = False,
    protected_image_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Prune unused Docker images without removing images referenced by running containers."""
    if hours <= 0:
        return {"ok": True, "skipped": True, "reason": "disabled", "hours": hours}
    if shutil.which("docker") is None:
        return {"ok": False, "skipped": True, "error": "docker_not_found", "hours": hours}
    protected = set(protected_image_ids or [])
    until = f"{int(hours)}h"
    if prune_unused_all:
        argv = ["docker", "image", "prune", "-a", "-f", "--filter", f"until={until}"]
    elif prune_dangling:
        argv = ["docker", "image", "prune", "-f", "--filter", f"until={until}"]
    else:
        return {"ok": True, "skipped": True, "reason": "no_prune_mode", "hours": hours}
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "error": str(ex)[:800], "hours": hours}
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    post_ids: set[str] = set()
    try:
        r2 = subprocess.run(["docker", "ps", "-q"], capture_output=True, text=True, timeout=60)
        if r2.returncode == 0:
            for cid in (r2.stdout or "").splitlines():
                cid = cid.strip()
                if not cid:
                    continue
                r3 = subprocess.run(
                    ["docker", "inspect", "--format", "{{.Image}}", cid],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if r3.returncode == 0 and r3.stdout.strip():
                    post_ids.add(r3.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    lost = sorted(protected - post_ids)
    return {
        "ok": r.returncode == 0 and not lost,
        "hours": hours,
        "prune_unused_all": prune_unused_all,
        "prune_dangling": prune_dangling,
        "returncode": r.returncode,
        "stdout": out[:4000],
        "stderr": err[:2000],
        "lost_running_image_ids": lost,
    }
