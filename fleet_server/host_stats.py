"""Read-only host metrics (stdlib only; Linux-friendly)."""

from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _parse_csv_int(s: str) -> int | None:
    s = (s or "").strip()
    if s in ("[N/A]", "", "N/A"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def nvidia_gpu_snapshot() -> dict[str, Any]:
    """NVIDIA GPUs via ``nvidia-smi`` when available (no extra Python deps)."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"available": False, "reason": "nvidia-smi not in PATH"}
    try:
        r = subprocess.run(
            [
                smi,
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"available": False, "reason": str(ex)[:240]}
    if r.returncode != 0:
        msg = (r.stderr or r.stdout or "nvidia-smi failed").strip()
        return {"available": False, "reason": msg[:500]}
    devices: list[dict[str, Any]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = next(csv.reader(io.StringIO(line)))
        except csv.Error:
            continue
        if len(row) < 6:
            continue
        idx = _parse_csv_int(row[0])
        name = row[1].strip()
        util = _parse_csv_int(row[2])
        mem_u = _parse_csv_int(row[3])
        mem_t = _parse_csv_int(row[4])
        temp = _parse_csv_int(row[5])
        mem_pct: float | None = None
        if mem_u is not None and mem_t is not None and mem_t > 0:
            mem_pct = round(100.0 * mem_u / mem_t, 1)
        devices.append(
            {
                "index": idx,
                "name": name,
                "utilization_pct": util,
                "memory_used_mib": mem_u,
                "memory_total_mib": mem_t,
                "memory_used_pct": mem_pct,
                "temperature_c": temp,
            }
        )
    if not devices:
        return {"available": False, "reason": "no GPU rows from nvidia-smi"}
    return {"available": True, "backend": "nvidia-smi", "devices": devices}


def _parse_meminfo_kb(text: str, key: str) -> int | None:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def snapshot() -> dict[str, Any]:
    """Lightweight machine snapshot for admin dashboard."""
    now = datetime.now(UTC).isoformat()
    out: dict[str, Any] = {
        "time_utc": now,
        "uptime_server_s": time.monotonic(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "cpus": os.cpu_count(),
    }
    if sys.platform.startswith("linux"):
        try:
            la = Path("/proc/loadavg").read_text(encoding="utf-8").split()
            out["loadavg"] = [float(la[0]), float(la[1]), float(la[2])] if len(la) >= 3 else la
        except OSError:
            out["loadavg"] = None
        try:
            mi = Path("/proc/meminfo").read_text(encoding="utf-8")
            total = _parse_meminfo_kb(mi, "MemTotal")
            avail = _parse_meminfo_kb(mi, "MemAvailable") or _parse_meminfo_kb(mi, "MemFree")
            mem: dict[str, Any] = {}
            if total:
                mem["total_kb"] = total
            if avail is not None and total:
                mem["available_kb"] = avail
                mem["used_pct"] = round(100.0 * (total - avail) / total, 1)
            out["memory"] = mem or None
        except OSError:
            out["memory"] = None
    else:
        out["loadavg"] = None
        out["memory"] = None
    out["gpu"] = nvidia_gpu_snapshot()
    return out
