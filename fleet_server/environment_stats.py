"""Docker stats telemetry for Fleet environment records (Postgres + container counts)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import env_templates, environments, managed_compose_service as mcs

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"ts": 0.0, "rows": []}
_CACHE_TTL_S = 8.0

_MEM_RE = re.compile(r"^([\d.]+)\s*([KMG]?)i?B?\s*/\s*([\d.]+)\s*([KMG]?)i?B?", re.I)


def _parse_mem_pair(raw: str) -> tuple[int | None, int | None, float | None]:
    text = str(raw or "").strip()
    if not text:
        return None, None, None
    m = _MEM_RE.match(text)
    if not m:
        return None, None, None

    def _to_bytes(value: str, unit: str) -> int:
        v = float(value)
        u = unit.upper()
        if u == "G":
            return int(v * 1024**3)
        if u == "M":
            return int(v * 1024**2)
        if u == "K":
            return int(v * 1024)
        return int(v)

    used = _to_bytes(m.group(1), m.group(2))
    limit = _to_bytes(m.group(3), m.group(4))
    pct = round(100.0 * used / limit, 2) if limit > 0 else None
    return used, limit, pct


def _parse_cpu_pct(raw: str) -> float | None:
    text = str(raw or "").strip().rstrip("%")
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def docker_stats_map(container_names: list[str], *, timeout: float = 12.0) -> dict[str, dict[str, Any]]:
    names = [n.strip() for n in container_names if str(n or "").strip()]
    if not names:
        return {}
    cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or row.get("Container") or "").strip()
        if not name:
            continue
        used, limit, mem_pct = _parse_mem_pair(str(row.get("MemUsage") or ""))
        out[name] = {
            "container_name": name,
            "cpu_pct": _parse_cpu_pct(str(row.get("CPUPerc") or "")),
            "mem_usage_bytes": used,
            "mem_limit_bytes": limit,
            "mem_pct": mem_pct,
            "net_io": str(row.get("NetIO") or "") or None,
            "block_io": str(row.get("BlockIO") or "") or None,
            "pids": int(row["PIDs"]) if str(row.get("PIDs") or "").isdigit() else None,
            "state": "running",
        }
    return out


def _postgres_service_name(record: dict[str, Any]) -> str:
    tpl = env_templates.get_template(str(record.get("template_id") or ""))
    if tpl:
        return str(tpl.get("postgres_service_name") or "postgres")
    return "postgres"


def _find_postgres_container(rows: list[dict[str, Any]], postgres_service: str) -> str | None:
    needle = postgres_service.lower()
    for row in rows:
        if not isinstance(row, dict):
            continue
        service = str(row.get("Service") or "").lower()
        name = str(row.get("Name") or "")
        if service == needle or needle in service or needle in name.lower():
            if name:
                return name
    return None


def _record_compose_status(record: dict[str, Any]) -> dict[str, Any]:
    try:
        return mcs.status_for_record(record)
    except (ValueError, FileNotFoundError, OSError, TypeError) as ex:
        return {
            "ps_ok": False,
            "services_running": 0,
            "services_total": 0,
            "last_error": str(ex)[:400],
            "services": [],
        }


def environment_telemetry_row(data_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    env_id = str(record.get("env_id") or "")
    rid = str(record.get("id") or "")
    state = str(record.get("state") or "unknown")
    st = _record_compose_status(record)
    root = Path(str(record.get("compose_root") or ""))
    rel = list(record.get("compose_files") or [])
    rows, _err = mcs.compose_ps(root, mcs.resolve_compose_files(root, rel)) if root.is_dir() else ([], None)
    postgres_service = _postgres_service_name(record)
    postgres_container = _find_postgres_container(rows, postgres_service)
    postgres_stats: dict[str, Any] | None = None
    if postgres_container:
        stats = docker_stats_map([postgres_container])
        postgres_stats = stats.get(postgres_container)
        if postgres_stats:
            postgres_stats = dict(postgres_stats)
            postgres_stats["container"] = postgres_container
            postgres_stats["service"] = postgres_service
    row: dict[str, Any] = {
        "id": rid,
        "env_id": env_id,
        "label": str(record.get("label") or env_id),
        "state": state,
        "containers_total": int(st.get("services_total") or 0),
        "containers_running": int(st.get("services_running") or 0),
        "ports": dict(record.get("ports") or {}),
        "gateway_slug": record.get("gateway_slug"),
        "postgres": postgres_stats,
    }
    return row


def environment_telemetry_snapshot(
    data_dir: Path,
    *,
    use_cache: bool = True,
) -> list[dict[str, Any]]:
    now = time.time()
    if use_cache:
        with _CACHE_LOCK:
            if now - float(_CACHE.get("ts") or 0) < _CACHE_TTL_S:
                cached = _CACHE.get("rows")
                if isinstance(cached, list):
                    return list(cached)
    recs = environments.list_records(data_dir)
    rows: list[dict[str, Any]] = []
    postgres_names: list[str] = []
    pending: list[tuple[dict[str, Any], str | None]] = []
    for rec in recs:
        state = str(rec.get("state") or "")
        if state not in ("ready", "running", "stopped"):
            continue
        root = Path(str(rec.get("compose_root") or ""))
        if not root.is_dir():
            continue
        try:
            rel = mcs.resolve_compose_files(root, list(rec.get("compose_files") or []))
        except (ValueError, FileNotFoundError, OSError):
            continue
        ps_rows, _ = mcs.compose_ps(root, rel)
        postgres_service = _postgres_service_name(rec)
        postgres_container = _find_postgres_container(ps_rows, postgres_service)
        pending.append((rec, postgres_container))
        if postgres_container:
            postgres_names.append(postgres_container)
    stats_by_name = docker_stats_map(sorted(set(postgres_names)))
    for rec, postgres_container in pending:
        row = environment_telemetry_row(data_dir, rec)
        if postgres_container and postgres_container in stats_by_name:
            pg = dict(stats_by_name[postgres_container])
            pg["container"] = postgres_container
            pg["service"] = _postgres_service_name(rec)
            row["postgres"] = pg
        rows.append(row)
    with _CACHE_LOCK:
        _CACHE["ts"] = now
        _CACHE["rows"] = list(rows)
    return rows


def granite_postgres_flat(telemetry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten per-env postgres stats for dock tabbed tile when no env groups."""
    out: list[dict[str, Any]] = []
    for env in telemetry:
        pg = env.get("postgres")
        if not isinstance(pg, dict):
            continue
        out.append(
            {
                "env_id": env.get("env_id"),
                "container": pg.get("container"),
                "cpu_pct": pg.get("cpu_pct"),
                "mem_pct": pg.get("mem_pct"),
                "pids": pg.get("pids"),
            }
        )
    return out
