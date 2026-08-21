"""Operate forge-llm **managed** Docker Compose stacks (``docker compose`` CLI)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fleet_server import managed_compose_service as mcs

# Re-export generic compose helpers for backward compatibility.
resolve_compose_files = mcs.resolve_compose_files
compose_ps = mcs.compose_ps
start_for_record = mcs.start_for_record
stop_for_record = mcs.stop_for_record
compose_argv = mcs.compose_argv


def gateway_host_port_from_compose_ps(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Parse ``docker compose ps --format json`` rows for ``forge-gateway`` published ``8080`` port.

    Typical ``Ports`` string: ``0.0.0.0:18080->8080/tcp`` or ``[::]:18080->8080/tcp``.
    """
    pat = re.compile(
        r"(?:^|[\s,])(?:0\.0\.0\.0|\:\:|\:\:\:|127\.0\.0\.1)\:(\d+)->8080/(?:tcp|udp)",
        re.I,
    )
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Service") or row.get("Name") or "").lower()
        if "forge-gateway" not in name and "gateway" not in name:
            continue
        ports = str(row.get("Ports") or "")
        m = pat.search(ports)
        if not m:
            continue
        try:
            hp = int(m.group(1))
        except ValueError:
            continue
        return {"host_port": hp, "container_port": 8080, "ports_preview": ports[:240]}
    return None


def fetch_gateway_control_plane(host_port: int, *, timeout: float = 3.0) -> dict[str, Any] | None:
    """Best-effort scrape of forge-gateway ``/v1/llm/stats`` from Fleet host."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{int(host_port)}/v1/llm/stats?hours=1"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TypeError):
        return None


def status_for_record(record: dict[str, Any]) -> dict[str, Any]:
    out = mcs.status_for_record(record)
    root = Path(str(out.get("compose_root") or "")).resolve()
    rel = list(out.get("compose_files") or [])
    if not rel:
        raw_cf = record.get("compose_files")
        extras = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else []
        rel = mcs.resolve_compose_files(root, extras)
    rows, _err = mcs.compose_ps(root, rel)
    gw = gateway_host_port_from_compose_ps(rows)
    if gw:
        out["gateway_publish"] = gw
        cp = fetch_gateway_control_plane(int(gw["host_port"]))
        if cp:
            out["control_plane"] = cp
    return out


def root_from_env() -> Path | None:
    raw = str(os.environ.get("FLEET_FORGE_LLM_ROOT") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if not p.is_dir() or not (p / "compose.yaml").is_file():
        return None
    return p
