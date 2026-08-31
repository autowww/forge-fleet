"""Operate forge-llm **managed** Docker Compose stacks (``docker compose`` CLI)."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import managed_compose_service as mcs

# Re-export generic compose helpers for backward compatibility.
resolve_compose_files = mcs.resolve_compose_files
compose_ps = mcs.compose_ps
start_for_record = mcs.start_for_record
stop_for_record = mcs.stop_for_record
compose_argv = mcs.compose_argv

_TOKENS_RATE_LOCK = threading.Lock()
_TOKENS_RATE_STATE: dict[str, tuple[float, int]] = {}


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


def fetch_gateway_control_plane(
    host_port: int,
    *,
    hours: float = 1.0,
    timeout: float = 3.0,
) -> dict[str, Any] | None:
    """Best-effort scrape of forge-gateway ``/v1/llm/stats`` from Fleet host."""
    import urllib.error
    import urllib.request

    window = max(0.01, float(hours))
    url = f"http://127.0.0.1:{int(host_port)}/v1/llm/stats?hours={window}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, TypeError):
        return None


def tokens_per_sec(service_id: str, completion_tokens: int) -> float | None:
    now = time.time()
    with _TOKENS_RATE_LOCK:
        prev = _TOKENS_RATE_STATE.get(service_id)
        _TOKENS_RATE_STATE[service_id] = (now, int(completion_tokens))
    if not prev:
        return None
    dt = now - prev[0]
    if dt <= 0:
        return None
    delta = int(completion_tokens) - prev[1]
    if delta < 0:
        return None
    return round(delta / dt, 2)


def build_llm_rack(
    control_plane: dict[str, Any],
    *,
    service_id: str,
    rollup_1h: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rollup = control_plane.get("rollup") if isinstance(control_plane.get("rollup"), dict) else {}
    active = control_plane.get("active") if isinstance(control_plane.get("active"), dict) else {}
    r1 = rollup_1h if isinstance(rollup_1h, dict) else rollup
    completion_tokens = int(rollup.get("completion_tokens") or 0)
    return {
        "active_model": active.get("active_model"),
        "active_mode": active.get("active_mode"),
        "queue_depth": control_plane.get("queue_depth"),
        "requests_1h": r1.get("requests"),
        "avg_total_ms_1h": r1.get("avg_total_ms"),
        "swaps_1h": r1.get("swaps"),
        "requests_since_fleet_start": rollup.get("requests"),
        "prompt_tokens_since_fleet_start": rollup.get("prompt_tokens"),
        "completion_tokens_since_fleet_start": completion_tokens,
        "tokens_per_sec": tokens_per_sec(service_id, completion_tokens),
    }


def status_for_record(
    record: dict[str, Any],
    *,
    fleet_started_epoch: float | None = None,
) -> dict[str, Any]:
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
        port = int(gw["host_port"])
        uptime_h = 1.0
        if fleet_started_epoch is not None:
            uptime_h = max(0.01, (time.time() - float(fleet_started_epoch)) / 3600.0)
        cp_start = fetch_gateway_control_plane(port, hours=uptime_h)
        cp_1h = cp_start
        if uptime_h > 1.05:
            cp_1h = fetch_gateway_control_plane(port, hours=1.0) or cp_start
        if cp_start:
            cp_start = dict(cp_start)
            if cp_1h and cp_1h is not cp_start:
                r1 = cp_1h.get("rollup") if isinstance(cp_1h.get("rollup"), dict) else {}
                cp_start["rollup_1h"] = r1
            out["control_plane"] = cp_start
    return out


def root_from_env() -> Path | None:
    raw = str(os.environ.get("FLEET_FORGE_LLM_ROOT") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if not p.is_dir() or not (p / "compose.yaml").is_file():
        return None
    return p
