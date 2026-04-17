"""Operate forge-llm **managed** Docker Compose stacks (``docker compose`` CLI)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

_ALLOWED_COMPOSE_FILES = frozenset(
    {
        "compose.yaml",
        "compose.cpu.yaml",
        "compose.gpu.yaml",
        "compose.observability-ports.yaml",
        "compose.observability-dcgm.yaml",
    }
)

_LOCK = threading.Lock()


def _compose_root_from_record(record: dict[str, Any]) -> Path:
    raw = str(record.get("compose_root") or "").strip()
    if not raw:
        raise ValueError("compose_root_missing")
    p = Path(raw).expanduser().resolve()
    if not p.is_dir():
        raise ValueError("compose_root_not_a_directory")
    if not (p / "compose.yaml").is_file():
        raise ValueError("compose_yaml_missing")
    return p


def resolve_compose_files(root: Path, compose_files: list[str]) -> list[str]:
    """``compose.yaml`` first, then validated overlay filenames that exist on disk."""
    files = ["compose.yaml"]
    seen: set[str] = {"compose.yaml"}
    for item in compose_files:
        n = Path(str(item).strip()).name
        if not n or n == "compose.yaml":
            continue
        if n not in _ALLOWED_COMPOSE_FILES:
            raise ValueError(f"compose_file_not_allowed:{n}")
        if n in seen:
            continue
        if not (root / n).is_file():
            raise FileNotFoundError(n)
        files.append(n)
        seen.add(n)
    return files


def _compose_argv(root: Path, rel_files: list[str]) -> list[str]:
    argv = ["docker", "compose"]
    for f in rel_files:
        argv.extend(["-f", str((root / f).resolve())])
    return argv


def compose_ps(root: Path, rel_files: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    """Parse ``docker compose ps -a --format json`` (one JSON object per line)."""
    cmd = _compose_argv(root, rel_files) + ["ps", "-a", "--format", "json"]
    try:
        r = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=90,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return [], str(ex)[:2000]
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        return [], err[:2000] or "compose_ps_failed"
    rows: list[dict[str, Any]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict):
            rows.append(o)
    return rows, None


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


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    running = 0
    slim: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("Name") or row.get("Service") or "").strip()
        state = str(row.get("State") or "").strip()
        health = row.get("Health")
        if isinstance(state, str) and state.lower() == "running":
            running += 1
        slim.append(
            {
                "name": name or None,
                "state": state or None,
                "health": health if isinstance(health, str) else None,
            }
        )
    return {
        "services_total": len(rows),
        "services_running": running,
        "services": slim[:32],
    }


def status_for_record(record: dict[str, Any]) -> dict[str, Any]:
    root = _compose_root_from_record(record)
    raw_cf = record.get("compose_files")
    extras = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else []
    rel = resolve_compose_files(root, extras)
    rows, err = compose_ps(root, rel)
    summary = _summarize_rows(rows)
    gw = gateway_host_port_from_compose_ps(rows)
    out = {
        "ok": True,
        "service_id": record.get("id"),
        "compose_root": str(root),
        "compose_files": rel,
        "ps_ok": err is None,
        "last_error": err,
        **summary,
    }
    if gw:
        out["gateway_publish"] = gw
    return out


def start_for_record(record: dict[str, Any]) -> dict[str, Any]:
    root = _compose_root_from_record(record)
    raw_cf = record.get("compose_files")
    extras = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else []
    rel = resolve_compose_files(root, extras)
    cmd = _compose_argv(root, rel) + ["up", "-d"]
    with _LOCK:
        try:
            r = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=900,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as ex:
            return {
                "ok": False,
                "error": "compose_up_failed",
                "detail": str(ex)[:2000],
                "compose_files": rel,
                "service_id": record.get("id"),
            }
        ok = r.returncode == 0
        return {
            "ok": ok,
            "service_id": record.get("id"),
            "compose_files": rel,
            "returncode": r.returncode,
            "stdout": (r.stdout or "").strip()[-8000:],
            "stderr": (r.stderr or "").strip()[-8000:],
        }


def stop_for_record(record: dict[str, Any]) -> dict[str, Any]:
    root = _compose_root_from_record(record)
    raw_cf = record.get("compose_files")
    extras = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else []
    rel = resolve_compose_files(root, extras)
    cmd = _compose_argv(root, rel) + ["down"]
    with _LOCK:
        try:
            r = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=600,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as ex:
            return {
                "ok": False,
                "error": "compose_down_failed",
                "detail": str(ex)[:2000],
                "compose_files": rel,
                "service_id": record.get("id"),
            }
        ok = r.returncode == 0
        return {
            "ok": ok,
            "service_id": record.get("id"),
            "compose_files": rel,
            "returncode": r.returncode,
            "stdout": (r.stdout or "").strip()[-8000:],
            "stderr": (r.stderr or "").strip()[-8000:],
        }


# --- legacy env helpers (migration + tests) ---------------------------------

def root_from_env() -> Path | None:
    raw = str(os.environ.get("FLEET_FORGE_LLM_ROOT") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    if not p.is_dir() or not (p / "compose.yaml").is_file():
        return None
    return p
