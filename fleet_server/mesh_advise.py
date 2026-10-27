"""Offload planning advice from Fleet marks and link throughput."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from fleet_server import host_profile, peer_links


def advise(
    data_dir: Path,
    db_path: Path,
    *,
    service_id: str,
    cpu_seconds: float,
    transfer_mb: float,
) -> dict[str, Any]:
    if cpu_seconds <= 0 or transfer_mb < 0:
        return {"ok": False, "error": "invalid_input"}
    local_prof = host_profile.load_profile(data_dir) or {}
    local_bench = (local_prof.get("benchmark") or {}) if isinstance(local_prof.get("benchmark"), dict) else {}
    local_mark = float(local_bench.get("fleet_mark") or 1000.0)
    local_bv = int(local_bench.get("bench_version") or 1)

    links = peer_links.mesh_links_payload(db_path, data_dir)
    candidates: list[dict[str, Any]] = []

    local_transfer = 0.0
    local_total = cpu_seconds + local_transfer
    candidates.append(
        {
            "node_id": socket.gethostname(),
            "scope": "local",
            "expected_cpu_seconds": cpu_seconds,
            "transfer_seconds": local_transfer,
            "total_seconds": local_total,
            "speedup_vs_local": 1.0,
            "reason": "Run on primary node (no transfer).",
        }
    )

    from fleet_server import remote_peers

    for peer in remote_peers.list_peers(data_dir).get("peers") or []:
        pid = str(peer.get("id") or "")
        edge = next((e for e in links.get("edges") or [] if e.get("peer_id") == pid), None)
        stats = (edge or {}).get("stats_1h") or {}
        mbps = stats.get("throughput_mbps_avg") or stats.get("throughput_mbps_max")
        if not mbps or mbps <= 0:
            continue
        transfer_s = (transfer_mb * 8) / float(mbps)
        peer_mark = local_mark
        code, body, _ = remote_peers.proxy_get(data_dir, pid, "/v1/host/profile")
        if 200 <= code < 300:
            import json

            try:
                doc = json.loads(body.decode("utf-8"))
                bench = (doc.get("benchmark") or {}) if isinstance(doc.get("benchmark"), dict) else {}
                if int(bench.get("bench_version") or 0) != local_bv:
                    continue
                peer_mark = float(bench.get("fleet_mark") or local_mark)
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        cpu_s = cpu_seconds * (local_mark / max(peer_mark, 1.0))
        total = transfer_s + cpu_s
        speedup = local_total / max(total, 1e-6)
        candidates.append(
            {
                "node_id": pid,
                "scope": "peer",
                "expected_cpu_seconds": round(cpu_s, 3),
                "transfer_seconds": round(transfer_s, 3),
                "total_seconds": round(total, 3),
                "speedup_vs_local": round(speedup, 3),
                "reason": f"Link ~{mbps:.1f} Mb/s; peer mark {int(peer_mark)} vs local {int(local_mark)}.",
            }
        )

    ranked = sorted(candidates, key=lambda r: r["total_seconds"])
    return {"ok": True, "service_id": service_id, "ranked": ranked, "best": ranked[0] if ranked else None}


def advise_agentic_dev(data_dir: Path, db_path: Path) -> dict[str, Any]:
    """Capacity-based placement for ``agentic_dev`` containers (no transfer: git is the carrier).

    Ranks local then peers by free slots; only nodes advertising ``agentic_dev: true`` qualify.
    """
    from fleet_server import agentic_dev_job, remote_peers

    local = agentic_dev_job.local_capacity(db_path)
    candidates: list[dict[str, Any]] = [
        {
            "node_id": "local",
            "scope": "local",
            "agentic_dev": bool(local.get("agentic_dev")),
            "free": int(local.get("free") or 0),
            "max_running": int(local.get("max_running") or 0),
            "reason": "Local node; clone from GitHub, no bundle transfer.",
        }
    ]
    for peer in remote_peers.list_peers(data_dir).get("peers") or []:
        pid = str(peer.get("id") or "")
        if not pid:
            continue
        cap = agentic_dev_job.peer_capacity(data_dir, pid)
        if cap.get("http") != 200:
            continue
        candidates.append(
            {
                "node_id": pid,
                "scope": "peer",
                "agentic_dev": bool(cap.get("agentic_dev")),
                "free": int(cap.get("free") or 0),
                "max_running": int(cap.get("max_running") or 0),
                "reason": "Peer capacity via /v1/admin/agentic-dev/capacity.",
            }
        )
    eligible = [c for c in candidates if c["agentic_dev"] and c["free"] > 0]
    ranked = sorted(eligible, key=lambda c: (c["scope"] != "local", -c["free"]))
    return {
        "ok": True,
        "workload": "agentic_dev",
        "ranked": ranked,
        "best": ranked[0] if ranked else None,
        "candidates": candidates,
    }
