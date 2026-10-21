"""Per-service primary/secondary vision over remote peers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fleet_server import host_profile, peer_links, remote_peers


def _service_ids(data_dir: Path) -> list[str]:
    etc = data_dir / "etc" / "services"
    if not etc.is_dir():
        return []
    return [p.stem for p in etc.glob("*.json")]


def vision_payload(data_dir: Path, db_path: Path, service_id: str) -> dict[str, Any]:
    import socket

    svc_path = data_dir / "etc" / "services" / f"{service_id}.json"
    if not svc_path.is_file():
        return {"ok": False, "error": "not_found"}
    try:
        svc = json.loads(svc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        svc = {}
    links = peer_links.mesh_links_payload(db_path, data_dir)
    secondaries = []
    for peer in remote_peers.list_peers(data_dir).get("peers") or []:
        pid = str(peer.get("id") or "")
        edge = next((e for e in links.get("edges") or [] if e.get("peer_id") == pid), None)
        prof = None
        code, body, _ = remote_peers.proxy_get(data_dir, pid, "/v1/host/profile")
        if 200 <= code < 300:
            try:
                prof = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                prof = None
        secondaries.append(
            {
                "peer_id": pid,
                "label": peer.get("label") or pid,
                "ready": edge is not None and bool((edge.get("stats_1h") or {}).get("throughput_mbps_avg")),
                "link": edge,
                "profile": prof,
            }
        )
    return {
        "ok": True,
        "service_id": service_id,
        "service": svc,
        "primary_node_id": socket.gethostname(),
        "secondaries": secondaries,
        "local_profile": host_profile.profile_payload(data_dir, db_path),
    }
