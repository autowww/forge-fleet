"""Per-node and mesh capacity headroom for planning (R20/R23 slice — no reservation ledger)."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any

from fleet_server import host_stats, remote_peers

_MESH_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}
_MESH_CACHE_TTL_S = 20.0


def _parse_gpu_reserved_env() -> dict[int, int]:
    """``FLEET_GPU_RESERVED`` JSON: ``[{index, vram_mb, label?}, ...]``."""
    raw = str(os.environ.get("FLEET_GPU_RESERVED") or "").strip()
    if not raw:
        return {}
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(doc, list):
        return {}
    out: dict[int, int] = {}
    for row in doc:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("index"))
            mb = int(row.get("vram_mb", 0))
        except (TypeError, ValueError):
            continue
        if mb > 0:
            out[idx] = out.get(idx, 0) + mb
    return out


def _cpu_block(host: dict[str, Any]) -> dict[str, Any]:
    cores_logical = host.get("cpus")
    try:
        cores_logical_i = int(cores_logical) if cores_logical is not None else 0
    except (TypeError, ValueError):
        cores_logical_i = 0
    cores_physical = host.get("cpu_cores_physical")
    try:
        cores_physical_i = int(cores_physical) if cores_physical is not None else None
    except (TypeError, ValueError):
        cores_physical_i = None
    used_pct = host.get("cpu_usage_pct")
    try:
        used_f = float(used_pct) if used_pct is not None else None
    except (TypeError, ValueError):
        used_f = None
    available_cores: float | None = None
    if cores_logical_i > 0 and used_f is not None:
        available_cores = round(cores_logical_i * max(0.0, 1.0 - used_f / 100.0), 2)
    return {
        "cores_logical": cores_logical_i or None,
        "cores_physical": cores_physical_i,
        "used_pct": used_f,
        "available_cores": available_cores,
        "estimate": True,
    }


def _memory_block(host: dict[str, Any]) -> dict[str, Any]:
    mem = host.get("memory") if isinstance(host.get("memory"), dict) else {}
    total_kb = mem.get("total_kb")
    avail_kb = mem.get("available_kb")
    try:
        total_kb_i = int(total_kb) if total_kb is not None else None
    except (TypeError, ValueError):
        total_kb_i = None
    try:
        avail_kb_i = int(avail_kb) if avail_kb is not None else None
    except (TypeError, ValueError):
        avail_kb_i = None
    total_mb = round(total_kb_i / 1024) if total_kb_i else None
    avail_mb = round(avail_kb_i / 1024) if avail_kb_i is not None else None
    used_mb: int | None = None
    if total_mb is not None and avail_mb is not None:
        used_mb = max(0, total_mb - avail_mb)
    return {
        "total_mb": total_mb,
        "used_mb": used_mb,
        "available_mb": avail_mb,
        "used_pct": mem.get("used_pct"),
        "reserved_mb": 0,
        "estimate": True,
    }


def _gpu_devices_from_bundle(gpu_bundle: dict[str, Any], reserved: dict[int, int]) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    nvidia = gpu_bundle.get("nvidia") if isinstance(gpu_bundle.get("nvidia"), dict) else {}
    if nvidia.get("available") and isinstance(nvidia.get("devices"), list):
        for dev in nvidia["devices"]:
            if not isinstance(dev, dict):
                continue
            idx = dev.get("index")
            try:
                idx_i = int(idx) if idx is not None else len(devices)
            except (TypeError, ValueError):
                idx_i = len(devices)
            vram_total = dev.get("memory_total_mib")
            vram_used = dev.get("memory_used_mib")
            try:
                total_mb = int(vram_total) if vram_total is not None else None
            except (TypeError, ValueError):
                total_mb = None
            try:
                used_mb = int(vram_used) if vram_used is not None else None
            except (TypeError, ValueError):
                used_mb = None
            reserved_mb = reserved.get(idx_i, 0)
            avail_mb: int | None = None
            if total_mb is not None:
                used_val = used_mb if used_mb is not None else 0
                avail_mb = max(0, total_mb - used_val - reserved_mb)
            devices.append(
                {
                    "index": idx_i,
                    "vendor": "nvidia",
                    "name": str(dev.get("name") or ""),
                    "utilization_pct": dev.get("utilization_pct"),
                    "vram_total_mb": total_mb,
                    "vram_used_mb": used_mb,
                    "vram_reserved_mb": reserved_mb,
                    "vram_available_mb": avail_mb,
                    "note": None,
                }
            )
    amdgpu = gpu_bundle.get("amdgpu_sysfs") if isinstance(gpu_bundle.get("amdgpu_sysfs"), dict) else {}
    if amdgpu.get("available") and isinstance(amdgpu.get("devices"), list):
        for dev in amdgpu["devices"]:
            if not isinstance(dev, dict):
                continue
            try:
                idx_i = int(dev.get("index", len(devices)))
            except (TypeError, ValueError):
                idx_i = len(devices)
            devices.append(
                {
                    "index": idx_i,
                    "vendor": "amd",
                    "name": "amdgpu",
                    "utilization_pct": dev.get("utilization_pct"),
                    "vram_total_mb": None,
                    "vram_used_mb": None,
                    "vram_reserved_mb": 0,
                    "vram_available_mb": None,
                    "note": "VRAM not exposed via amdgpu sysfs",
                }
            )
    rocm = gpu_bundle.get("rocm") if isinstance(gpu_bundle.get("rocm"), dict) else {}
    if rocm.get("available") and isinstance(rocm.get("devices"), list):
        for dev in rocm["devices"]:
            if not isinstance(dev, dict):
                continue
            try:
                idx_i = int(dev.get("index", len(devices)))
            except (TypeError, ValueError):
                idx_i = len(devices)
            devices.append(
                {
                    "index": idx_i,
                    "vendor": "amd",
                    "name": "rocm",
                    "utilization_pct": dev.get("utilization_pct"),
                    "vram_total_mb": None,
                    "vram_used_mb": None,
                    "vram_reserved_mb": 0,
                    "vram_available_mb": None,
                    "note": "VRAM not exposed via rocm-smi",
                }
            )
    intel = gpu_bundle.get("intel_drm_est") if isinstance(gpu_bundle.get("intel_drm_est"), dict) else {}
    if intel.get("available") and isinstance(intel.get("devices"), list):
        for dev in intel["devices"]:
            if not isinstance(dev, dict):
                continue
            try:
                idx_i = int(dev.get("index", len(devices)))
            except (TypeError, ValueError):
                idx_i = len(devices)
            devices.append(
                {
                    "index": idx_i,
                    "vendor": "intel",
                    "name": "intel_drm",
                    "utilization_pct": dev.get("utilization_pct_est") or dev.get("utilization_pct"),
                    "vram_total_mb": None,
                    "vram_used_mb": None,
                    "vram_reserved_mb": 0,
                    "vram_available_mb": None,
                    "note": "Intel DRM busy estimate only",
                }
            )
    return devices


def from_host_snapshot(host: dict[str, Any]) -> dict[str, Any]:
    """Map ``host_stats.snapshot()`` to planning headroom blocks."""
    gpu_bundle = host.get("gpu") if isinstance(host.get("gpu"), dict) else {}
    reserved_map = _parse_gpu_reserved_env()
    return {
        "cpu": _cpu_block(host),
        "memory": _memory_block(host),
        "gpu": _gpu_devices_from_bundle(gpu_bundle, reserved_map),
        "reservations": [],
        "planning_note": "Headroom estimates only; job reservation ledger not active.",
    }


def _node_role(data_dir: Path | None) -> str:
    if data_dir is None:
        return "unknown"
    try:
        from fleet_server import operator_ui_settings

        doc = operator_ui_settings.get_settings(data_dir)
        return str((doc.get("settings") or {}).get("machine_role") or "laptop")
    except Exception:
        return "unknown"


def capacity_payload(data_dir: Path | None = None) -> dict[str, Any]:
    host = host_stats.snapshot()
    return {
        "ok": True,
        "node_id": socket.gethostname(),
        "role": _node_role(data_dir),
        "degraded": False,
        "capacity": from_host_snapshot(host),
        "observed_at": time.time(),
    }


def mesh_capacity(data_dir: Path, cache_ttl_s: float = _MESH_CACHE_TTL_S) -> dict[str, Any]:
    global _MESH_CACHE
    now = time.time()
    cached = _MESH_CACHE.get("payload")
    cached_at = float(_MESH_CACHE.get("at") or 0.0)
    if cached is not None and (now - cached_at) < cache_ttl_s:
        out = json.loads(json.dumps(cached))
        out["cached"] = True
        out["cache_age_s"] = round(now - cached_at, 1)
        return out

    local = capacity_payload(data_dir)
    nodes: list[dict[str, Any]] = [
        {
            "scope": "local",
            "peer_id": None,
            "label": "Local",
            "ok": True,
            "probed_at": now,
            "capacity": local.get("capacity"),
            "node_id": local.get("node_id"),
            "role": local.get("role"),
            "degraded": local.get("degraded"),
        }
    ]
    listed = remote_peers.list_peers(data_dir)
    for peer in listed.get("peers") or []:
        if not isinstance(peer, dict):
            continue
        pid = str(peer.get("id") or "")
        label = str(peer.get("label") or pid)
        probed = time.time()
        code, body, _ctype = remote_peers.proxy_get(data_dir, pid, "/v1/capacity")
        row: dict[str, Any] = {
            "scope": "peer",
            "peer_id": pid,
            "label": label,
            "ok": False,
            "probed_at": probed,
        }
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if 200 <= code < 300 and isinstance(payload, dict) and payload.get("ok"):
            row["ok"] = True
            row["capacity"] = payload.get("capacity")
            row["node_id"] = payload.get("node_id")
            row["role"] = payload.get("role")
            row["degraded"] = payload.get("degraded")
        else:
            err = payload.get("error") if isinstance(payload, dict) else None
            row["error"] = err or ("http_" + str(code))
        nodes.append(row)

    payload = {
        "ok": True,
        "cached": False,
        "cache_ttl_s": cache_ttl_s,
        "observed_at": now,
        "nodes": nodes,
    }
    _MESH_CACHE = {"at": now, "payload": payload}
    return payload


def reset_mesh_capacity_cache() -> None:
    """Clear mesh capacity cache (tests only)."""
    global _MESH_CACHE
    _MESH_CACHE = {"at": 0.0, "payload": None}


def verify_public_health(public_url: str, bearer_token: str) -> dict[str, Any]:
    """Server-side GET ``/v1/health`` against a public Fleet URL (Edge tab verify)."""
    import ssl
    import urllib.error
    import urllib.request

    base = (public_url or "").strip().rstrip("/")
    if base.endswith("/v1/health"):
        url = base
    elif base.endswith("/v1"):
        url = base + "/health"
    else:
        url = base + "/v1/health" if base else ""
    if not url.startswith("http://") and not url.startswith("https://"):
        return {"ok": False, "error": "invalid_public_url"}
    token = (bearer_token or "").strip()
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=15.0, context=ctx) as resp:
            raw = resp.read()
            code = int(resp.status)
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        raw = exc.read() if exc.fp else b""
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return {"ok": False, "error": "upstream_unreachable", "detail": str(exc)[:500]}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"raw": raw.decode("utf-8", errors="replace")[:500]}
    ok = 200 <= code < 300 and isinstance(payload, dict) and payload.get("ok") is True
    return {
        "ok": ok,
        "http_status": code,
        "health": payload if isinstance(payload, dict) else None,
        "url": url,
    }
