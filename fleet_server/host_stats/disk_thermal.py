"""Read-only host metrics (stdlib only; Linux-friendly)."""

from __future__ import annotations

import csv
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fleet_server.host_stats.energy_cpu import (
    _parse_meminfo_kb,
    cpufreq_metrics,
    cpu_usage_percent_per_core_avg_sample,
    energy_observation,
    physical_cpu_cores_linux,
)
from fleet_server.host_stats.gpu import (
    amdgpu_junction_snapshot,
    gpu_bundle,
    intel_engine_busy_snapshot,
    linux_soc_junction_rated_sysfs,
)

_DISK_DEV = re.compile(r"^(sd[a-z]+|vd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")
_SPACE_FSTYPES = frozenset(
    {
        "ext2",
        "ext3",
        "ext4",
        "xfs",
        "btrfs",
        "zfs",
        "fuseblk",
        "fuse",
        "overlay",
        "nfs",
        "nfs4",
        "vfat",
        "msdos",
    }
)


def _diskstats_physical() -> dict[str, tuple[int, int, int]]:
    """Map device name -> (sectors_read, sectors_written, io_ticks_ms).

    ``io_ticks_ms`` is kernel field 13 (1-based) / ``parts[12]``: milliseconds the
    device was actively doing I/Os during the sample window. ``Δio_ticks / wall_ms``
    matches ``iostat`` %util (not ``time_in_queue`` / ``parts[13]``, which is weighted
    queue time and is *not* comparable to wall-clock ms the same way).
    """
    out: dict[str, tuple[int, int, int]] = {}
    try:
        text = Path("/proc/diskstats").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        if not _DISK_DEV.match(name):
            continue
        try:
            rsect = int(parts[5])
            wsect = int(parts[9])
            io_ticks = int(parts[12])
        except (ValueError, IndexError):
            continue
        out[name] = (rsect, wsect, io_ticks)
    return out


def disk_io_snapshot() -> dict[str, Any]:
    """Throughput + approximate busy%% from ``/proc/diskstats`` (two samples, ~120 ms)."""
    if not sys.platform.startswith("linux"):
        return {"available": False, "reason": "non-linux"}
    a = _diskstats_physical()
    if not a:
        return {"available": False, "reason": "no whole-disk lines in /proc/diskstats"}
    t0 = time.perf_counter_ns()
    time.sleep(0.12)
    t1 = time.perf_counter_ns()
    b = _diskstats_physical()
    dt_s = max(1e-6, (t1 - t0) / 1e9)
    wall_ms = (t1 - t0) / 1e6
    devices: list[dict[str, Any]] = []
    for name in sorted(set(a) & set(b)):
        r0, w0, t0_ticks = a[name]
        r1, w1, t1_ticks = b[name]
        dr = max(0, r1 - r0)
        dw = max(0, w1 - w0)
        d_ticks = max(0, t1_ticks - t0_ticks)
        read_mbps = (dr * 512) / (1024 * 1024) / dt_s
        write_mbps = (dw * 512) / (1024 * 1024) / dt_s
        busy_pct = min(100.0, max(0.0, 100.0 * d_ticks / wall_ms)) if wall_ms > 0 else None
        devices.append(
            {
                "device": name,
                "read_mbps": round(read_mbps, 2),
                "write_mbps": round(write_mbps, 2),
                "total_mbps": round(read_mbps + write_mbps, 2),
                "busy_pct_est": round(busy_pct, 1) if busy_pct is not None else None,
            }
        )
    devices.sort(key=lambda d: d["total_mbps"], reverse=True)
    agg_r = sum(d["read_mbps"] for d in devices)
    agg_w = sum(d["write_mbps"] for d in devices)
    busy_estimates = [d["busy_pct_est"] for d in devices if d.get("busy_pct_est") is not None]
    busy_max = max(busy_estimates) if busy_estimates else (0.0 if devices else None)
    return {
        "available": True,
        "sample_ms": round(wall_ms, 1),
        "devices": devices[:12],
        "aggregated": {
            "read_mbps": round(agg_r, 2),
            "write_mbps": round(agg_w, 2),
            "total_mbps": round(agg_r + agg_w, 2),
            "busy_pct_est_max": busy_max,
        },
    }


def disk_space_snapshot() -> list[dict[str, Any]]:
    """Per-mount usage for ``/`` and common paths when present in ``/proc/mounts``."""
    if not sys.platform.startswith("linux"):
        return []
    want: list[str] = ["/"]
    try:
        for line in Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mnt, fst = parts[1], parts[2]
            if fst not in _SPACE_FSTYPES:
                continue
            if mnt in ("/var", "/home") and mnt not in want:
                want.append(mnt)
    except OSError:
        pass
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for mnt in want:
        if mnt in seen:
            continue
        p = Path(mnt)
        try:
            if not p.is_dir():
                continue
            u = shutil.disk_usage(mnt)
        except OSError:
            continue
        seen.add(mnt)
        total = u.total or 1
        rows.append(
            {
                "mount": mnt,
                "total_gb": round(u.total / 1e9, 2),
                "used_gb": round(u.used / 1e9, 2),
                "free_gb": round(u.free / 1e9, 2),
                "used_pct": round(100.0 * u.used / total, 1),
            }
        )
    rows.sort(key=lambda d: (0 if d["mount"] == "/" else 1, d["mount"]))
    return rows


def thermal_cpu_snapshot() -> dict[str, Any]:
    """Best-effort CPU-ish temperature from Linux sysfs (millidegree C in thermal zones)."""
    if not sys.platform.startswith("linux"):
        return {"max_c": None, "source": "unavailable", "reason": "non-linux"}
    readings: list[tuple[float, str]] = []
    tz_root = Path("/sys/class/thermal")
    try:
        if tz_root.is_dir():
            for zdir in sorted(tz_root.glob("thermal_zone*"), key=lambda p: p.name):
                tpath = zdir / "temp"
                if not tpath.is_file():
                    continue
                typ = "zone"
                try:
                    nfile = zdir / "type"
                    if nfile.is_file():
                        typ = nfile.read_text(encoding="utf-8", errors="replace").strip() or "zone"
                except OSError:
                    pass
                try:
                    raw = int(tpath.read_text(encoding="utf-8", errors="replace").strip())
                except (OSError, ValueError):
                    continue
                c = raw / 1000.0
                if -55.0 < c < 130.0:
                    readings.append((c, f"thermal:{typ}"))
    except OSError:
        pass

    hwmon_labels = ("coretemp", "k10temp", "zenpower")
    try:
        hw = Path("/sys/class/hwmon")
        if hw.is_dir():
            for hdir in sorted(hw.glob("hwmon*"), key=lambda p: p.name):
                try:
                    label = (hdir / "name").read_text(encoding="utf-8", errors="replace").strip().lower()
                except OSError:
                    continue
                if not any(x in label for x in hwmon_labels):
                    continue
                for tp in sorted(hdir.glob("temp*_input")):
                    try:
                        raw = int(tp.read_text(encoding="utf-8", errors="replace").strip())
                    except (OSError, ValueError):
                        continue
                    c = raw / 1000.0
                    if -55.0 < c < 130.0:
                        readings.append((c, f"hwmon:{label}:{tp.name}"))
    except OSError:
        pass

    if not readings:
        out: dict[str, Any] = {"max_c": None, "source": "unavailable", "reason": "no thermal sysfs"}
        if sys.platform.startswith("linux"):
            out["arm_junction_rated"] = linux_soc_junction_rated_sysfs()
        return out
    best = max(readings, key=lambda t: t[0])
    out = {"max_c": round(best[0], 1), "source": best[1]}
    if sys.platform.startswith("linux"):
        out["arm_junction_rated"] = linux_soc_junction_rated_sysfs()
    return out


def snapshot() -> dict[str, Any]:
    """Lightweight machine snapshot for admin dashboard."""
    now = datetime.now(UTC).isoformat()
    out: dict[str, Any] = {
        "time_utc": now,
        "uptime_server_s": time.monotonic(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "machine": platform.machine(),
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
        try:
            up0 = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
            out["system_uptime_s"] = float(up0)
        except (OSError, ValueError, IndexError):
            out["system_uptime_s"] = None
        out["cpu_usage_pct"] = cpu_usage_percent_per_core_avg_sample(0.06)
        out.update(cpufreq_metrics())
        out["cpu_cores_physical"] = physical_cpu_cores_linux()
        out["disks"] = {"space": disk_space_snapshot(), "io": disk_io_snapshot()}
    else:
        out["loadavg"] = None
        out["memory"] = None
        out["system_uptime_s"] = None
        out["cpu_usage_pct"] = None
        out.update(cpufreq_metrics())
        out["cpu_cores_physical"] = None
        out["disks"] = {"space": [], "io": {"available": False, "reason": "non-linux"}}
    out["gpu"] = gpu_bundle()
    out["energy"] = energy_observation(out["gpu"])
    if sys.platform.startswith("linux"):
        out["thermal"] = thermal_cpu_snapshot()
    else:
        out["thermal"] = {"max_c": None, "source": "unavailable", "reason": "non-linux"}
    return out
