"""Read-only host metrics (stdlib only; Linux-friendly)."""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


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
    return out
