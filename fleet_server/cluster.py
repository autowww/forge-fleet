"""Mesh cluster view: capacity + managed services + container stats per node."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import capacity, container_layout, forge_llm_service, host_container_stats, managed_compose_service, remote_peers

_CLUSTER_LOCK = threading.Lock()
_CLUSTER_CACHE: dict[str, Any] = {"at": 0.0, "payload": None}
_CLUSTER_CACHE_TTL_S = 8.0
_PEER_STATS_TIMEOUT_S = 25.0


def _service_status(rec: dict[str, Any]) -> dict[str, Any] | None:
    if str(rec.get("type_id")) == "forge_llm":
        return forge_llm_service.status_for_record(rec)
    return managed_compose_service.status_for_record(rec)


def container_services_payload(data_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rec in container_layout.list_service_records(data_dir):
        row = dict(rec)
        type_id = str(rec.get("type_id") or "").strip()
        eff = container_layout.effective_type_by_id(data_dir, type_id)
        if eff is not None:
            caps = eff.get("effective_capabilities")
            if isinstance(caps, dict) and bool(caps.get("api_manage_services")):
                row["status"] = _service_status(rec)
        rows.append(row)
    return {
        "ok": True,
        "services": rows,
        "paths": container_layout.layout_paths_payload(data_dir),
    }


def _json_peer_payload(body: bytes, code: int) -> dict[str, Any] | None:
    if not (200 <= code < 300):
        return None
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _local_node(data_dir: Path, *, use_cache: bool) -> dict[str, Any]:
    cap = capacity.capacity_payload(data_dir)
    svc = container_services_payload(data_dir)
    stats = host_container_stats.container_stats_payload(use_cache=use_cache)
    partial_errors: list[str] = []
    if not stats.get("ok"):
        err = str(stats.get("docker_ps_error") or "container_stats_failed")
        partial_errors.append(err)
    return {
        "scope": "local",
        "peer_id": None,
        "label": "Local",
        "ok": len(partial_errors) == 0,
        "probed_at": time.time(),
        "node_id": cap.get("node_id"),
        "role": cap.get("role"),
        "capacity": cap.get("capacity"),
        "degraded": cap.get("degraded"),
        "services": svc.get("services") if isinstance(svc.get("services"), list) else [],
        "container_stats": stats,
        "errors": partial_errors,
    }


def _peer_node(data_dir: Path, peer: dict[str, Any], *, use_cache: bool) -> dict[str, Any]:
    pid = str(peer.get("id") or "")
    label = str(peer.get("label") or pid)
    probed = time.time()
    row: dict[str, Any] = {
        "scope": "peer",
        "peer_id": pid,
        "label": label,
        "ok": False,
        "probed_at": probed,
        "errors": [],
    }
    refresh_q = "" if use_cache else "?refresh=1"
    code, body, _ = remote_peers.proxy_get(data_dir, pid, "/v1/capacity")
    cap_doc = _json_peer_payload(body, code)
    if cap_doc and cap_doc.get("ok"):
        row["capacity"] = cap_doc.get("capacity")
        row["node_id"] = cap_doc.get("node_id")
        row["role"] = cap_doc.get("role")
        row["degraded"] = cap_doc.get("degraded")
    else:
        err = cap_doc.get("error") if isinstance(cap_doc, dict) else None
        row["errors"].append(err or f"capacity_http_{code}")

    code2, body2, _ = remote_peers.proxy_get(data_dir, pid, "/v1/container-services")
    svc_doc = _json_peer_payload(body2, code2)
    if svc_doc and svc_doc.get("ok"):
        row["services"] = svc_doc.get("services") if isinstance(svc_doc.get("services"), list) else []
    else:
        row["services"] = []
        err = svc_doc.get("error") if isinstance(svc_doc, dict) else None
        row["errors"].append(err or f"container_services_http_{code2}")

    stats_path = f"/v1/host/container-stats{refresh_q}"
    code3, body3, _ = remote_peers.proxy_get(
        data_dir,
        pid,
        stats_path,
        timeout_s=_PEER_STATS_TIMEOUT_S,
    )
    stats_doc = _json_peer_payload(body3, code3)
    if stats_doc:
        row["container_stats"] = stats_doc
        if not stats_doc.get("ok"):
            row["errors"].append(str(stats_doc.get("docker_ps_error") or f"container_stats_http_{code3}"))
    else:
        row["container_stats"] = {"ok": False, "containers": []}
        row["errors"].append(f"container_stats_http_{code3}")

    row["ok"] = len(row["errors"]) == 0
    if row["errors"]:
        row["error"] = row["errors"][0]
    return row


def cluster_payload(data_dir: Path, *, use_cache: bool = True, cache_ttl_s: float = _CLUSTER_CACHE_TTL_S) -> dict[str, Any]:
    now = time.time()
    if use_cache:
        with _CLUSTER_LOCK:
            cached = _CLUSTER_CACHE.get("payload")
            cached_at = float(_CLUSTER_CACHE.get("at") or 0.0)
            if isinstance(cached, dict) and (now - cached_at) < cache_ttl_s:
                out = json.loads(json.dumps(cached))
                out["cached"] = True
                out["cache_age_s"] = round(now - cached_at, 1)
                return out

    nodes: list[dict[str, Any]] = [_local_node(data_dir, use_cache=use_cache)]
    listed = remote_peers.list_peers(data_dir)
    for peer in listed.get("peers") or []:
        if not isinstance(peer, dict):
            continue
        full = remote_peers.get_peer(data_dir, str(peer.get("id") or ""))
        if full is None:
            continue
        nodes.append(_peer_node(data_dir, full, use_cache=use_cache))

    payload = {
        "ok": True,
        "observed_at": now,
        "cache_ttl_s": cache_ttl_s,
        "cached": False,
        "nodes": nodes,
    }
    with _CLUSTER_LOCK:
        _CLUSTER_CACHE["at"] = now
        _CLUSTER_CACHE["payload"] = json.loads(json.dumps(payload))
    return payload


def reset_cluster_cache() -> None:
    """Clear cluster cache (tests only)."""
    global _CLUSTER_CACHE
    _CLUSTER_CACHE = {"at": 0.0, "payload": None}