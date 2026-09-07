"""Host OS process listing via /proc (Linux; stdlib only)."""

from __future__ import annotations

import os
import re
import time
from typing import Any

_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50

_prev_sample: dict[int, tuple[float, int, int]] = {}
_last_wall_ts = 0.0


def _system_jiffies() -> int | None:
    try:
        line = open("/proc/stat", encoding="utf-8").readline()
        fields = [int(x) for x in line.split()[1:]]
        return sum(fields)
    except (OSError, ValueError):
        return None


def _cpu_count() -> int:
    try:
        return max(1, len(open("/proc/cpuinfo", encoding="utf-8").read().split("processor")))
    except OSError:
        return 1


def _read_stat(pid: int) -> tuple[str, int, int] | None:
    try:
        raw = open(f"/proc/{pid}/stat", encoding="utf-8").read()
    except OSError:
        return None
    close_paren = raw.rfind(")")
    if close_paren < 0:
        return None
    name = raw[raw.find("(") + 1 : close_paren]
    rest = raw[close_paren + 2 :].split()
    if len(rest) < 12:
        return None
    try:
        utime = int(rest[11])
        stime = int(rest[12])
    except (ValueError, IndexError):
        return None
    return name, utime, stime


def _read_cmdline(pid: int) -> str:
    try:
        raw = open(f"/proc/{pid}/cmdline", "rb").read()
    except OSError:
        return ""
    if not raw:
        return ""
    parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]
    cmd = " ".join(parts).strip()
    return cmd or ""


def _read_rss_kb(pid: int) -> int | None:
    try:
        for line in open(f"/proc/{pid}/status", encoding="utf-8"):
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1])
    except (OSError, ValueError):
        return None
    return None


def _total_mem_kb() -> int | None:
    try:
        for line in open("/proc/meminfo", encoding="utf-8"):
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1])
    except (OSError, ValueError):
        return None
    return None


def _cpu_pct_for_pid(pid: int, utime: int, stime: int, now: float, total: int) -> float | None:
    global _last_wall_ts
    cpu_ticks = utime + stime
    prev = _prev_sample.get(pid)
    _prev_sample[pid] = (now, cpu_ticks, total)
    if prev is None:
        return None
    prev_ts, prev_cpu, prev_total = prev
    dt = now - prev_ts
    if dt <= 0:
        return None
    cpu_delta = cpu_ticks - prev_cpu
    total_delta = total - prev_total
    if total_delta <= 0:
        return None
    cores = _cpu_count()
    pct = 100.0 * cpu_delta / total_delta / cores
    return max(0.0, min(100.0, pct))


def _list_pids() -> list[int]:
    if not os.path.isdir("/proc"):
        return []
    out: list[int] = []
    for name in os.listdir("/proc"):
        if re.fullmatch(r"\d+", name):
            out.append(int(name))
    return out


def snapshot(*, limit: int = _DEFAULT_LIMIT, sort: str = "cpu") -> dict[str, Any]:
    """Return top host processes by CPU or memory."""
    if not os.path.isdir("/proc"):
        return {
            "ok": False,
            "error": "unsupported_platform",
            "detail": "/proc not available",
            "processes": [],
        }

    t0 = time.perf_counter()
    lim = max(1, min(int(limit), _MAX_LIMIT))
    sort_key = (sort or "cpu").strip().lower()
    if sort_key not in ("cpu", "mem", "pid"):
        sort_key = "cpu"

    now = time.time()
    total_jiffies = _system_jiffies()
    mem_total = _total_mem_kb()

    rows: list[dict[str, Any]] = []
    for pid in _list_pids():
        stat = _read_stat(pid)
        if stat is None:
            continue
        name, utime, stime = stat
        rss_kb = _read_rss_kb(pid)
        cpu_pct: float | None = None
        if total_jiffies is not None:
            cpu_pct = _cpu_pct_for_pid(pid, utime, stime, now, total_jiffies)
        mem_pct: float | None = None
        if rss_kb is not None and mem_total and mem_total > 0:
            mem_pct = round(100.0 * rss_kb / mem_total, 2)
        cmd = _read_cmdline(pid) or name
        if len(cmd) > 280:
            cmd = cmd[:277] + "…"
        rows.append(
            {
                "pid": pid,
                "name": name,
                "cmd": cmd,
                "cpu_pct": round(cpu_pct, 1) if cpu_pct is not None else None,
                "mem_pct": mem_pct,
                "rss_kb": rss_kb,
            }
        )

    if sort_key == "mem":
        rows.sort(key=lambda r: (r.get("rss_kb") or 0, r.get("pid") or 0), reverse=True)
    elif sort_key == "pid":
        rows.sort(key=lambda r: r.get("pid") or 0)
    else:
        rows.sort(
            key=lambda r: (r.get("cpu_pct") if r.get("cpu_pct") is not None else -1.0, r.get("pid") or 0),
            reverse=True,
        )

    sample_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "sample_ms": sample_ms,
        "sort": sort_key,
        "limit": lim,
        "processes": rows[:lim],
    }
