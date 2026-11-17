"""Running-container CPU/memory via docker ps + docker stats (cached)."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

from fleet_server import environment_stats

_HOST_CONTAINER_STATS_SCHEMA = "forge.fleet.host_container_stats.v1"
_MAX_CONTAINERS = 80
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}


def _cache_ttl_s() -> float:
    try:
        v = float(os.environ.get("FLEET_HOST_CONTAINER_STATS_CACHE_TTL_S") or "8")
    except ValueError:
        return 8.0
    return max(5.0, v)


def _running_container_names(*, timeout: float = 8.0) -> tuple[list[str], str | None]:
    cmd = ["docker", "ps", "--filter", "status=running", "--format", "{{.Names}}"]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return [], str(ex)[:400]
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "docker_ps_failed").strip()[:400]
        return [], err or "docker_ps_failed"
    names: list[str] = []
    for line in (r.stdout or "").splitlines():
        name = line.strip()
        if name:
            names.append(name)
    return names, None


def container_stats_payload(*, use_cache: bool = True) -> dict[str, Any]:
    """Snapshot of running containers with live docker stats rows."""
    now = time.time()
    ttl = _cache_ttl_s()
    if use_cache:
        with _CACHE_LOCK:
            cached = _CACHE.get("payload")
            cached_at = float(_CACHE.get("ts") or 0.0)
            if isinstance(cached, dict) and (now - cached_at) < ttl:
                out = dict(cached)
                out["cached"] = True
                out["cache_age_s"] = round(now - cached_at, 1)
                return out

    names, ps_err = _running_container_names()
    truncated = len(names) > _MAX_CONTAINERS
    selected = names[:_MAX_CONTAINERS]
    stats_map = environment_stats.docker_stats_map(selected) if selected else {}
    containers: list[dict[str, Any]] = []
    for name in selected:
        row = stats_map.get(name)
        if row:
            containers.append(dict(row))
        else:
            containers.append(
                {
                    "container_name": name,
                    "cpu_pct": None,
                    "mem_usage_bytes": None,
                    "mem_limit_bytes": None,
                    "mem_pct": None,
                    "net_io": None,
                    "block_io": None,
                    "pids": None,
                    "state": "running",
                    "stats_missing": True,
                }
            )
    containers.sort(
        key=lambda c: (
            -(c.get("cpu_pct") or 0.0) if c.get("cpu_pct") is not None else -1.0,
            str(c.get("container_name") or ""),
        )
    )
    ok = ps_err is None
    payload: dict[str, Any] = {
        "ok": ok,
        "schema_version": _HOST_CONTAINER_STATS_SCHEMA,
        "observed_at": now,
        "containers_total_reported": len(names),
        "containers_included": len(selected),
        "truncated": truncated,
        "containers": containers,
        "docker_ps_error": ps_err,
        "cached": False,
    }
    if use_cache and ok:
        with _CACHE_LOCK:
            _CACHE["ts"] = now
            _CACHE["payload"] = dict(payload)
    return payload