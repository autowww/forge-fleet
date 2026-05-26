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


def rapl_package_energy_uj() -> dict[str, Any]:
    """
    Sum RAPL ``energy_uj`` for **package** domains only (skips ``core`` / ``uncore`` children)
    under ``/sys/class/powercap`` to avoid double-counting.
    """
    if not sys.platform.startswith("linux"):
        return {"available": False, "reason": "non-linux", "total_uj": None}
    root = Path("/sys/class/powercap")
    if not root.is_dir():
        return {"available": False, "reason": "no /sys/class/powercap", "total_uj": None}
    total = 0
    domains = 0
    read_err: str | None = None
    for z in sorted(root.iterdir()):
        if not z.is_dir():
            continue
        name_f = z / "name"
        ej_f = z / "energy_uj"
        if not ej_f.is_file():
            continue
        try:
            raw_name = name_f.read_text(encoding="utf-8", errors="replace").strip().lower() if name_f.is_file() else ""
        except OSError:
            raw_name = ""
        if "package" not in raw_name or "core" in raw_name:
            continue
        try:
            uj = int((ej_f.read_text(encoding="utf-8", errors="replace").strip()))
        except PermissionError:
            read_err = "permission denied reading RAPL energy_uj (run Fleet as root or adjust sysfs permissions)"
            continue
        except (OSError, ValueError) as e:
            if read_err is None:
                read_err = f"cannot read RAPL energy_uj: {e}"
            continue
        if uj < 0:
            continue
        total += uj
        domains += 1
    if domains == 0:
        reason = read_err or "no readable package RAPL energy_uj"
        return {"available": False, "reason": reason, "total_uj": None}
    return {"available": True, "domains": domains, "total_uj": total}


def rapl_package_power_uw_sum() -> int | None:
    """
    Sum ``power_uw`` (micro-watts) for **package** RAPL domains when the kernel exposes it.

    This is optional hardware/kernel support; when present it gives an immediate draw hint
    without waiting for a second ``energy_uj`` sample.
    """
    if not sys.platform.startswith("linux"):
        return None
    root = Path("/sys/class/powercap")
    if not root.is_dir():
        return None
    total = 0
    n = 0
    for z in sorted(root.iterdir()):
        if not z.is_dir():
            continue
        name_f = z / "name"
        pw_f = z / "power_uw"
        if not pw_f.is_file():
            continue
        try:
            raw_name = name_f.read_text(encoding="utf-8", errors="replace").strip().lower() if name_f.is_file() else ""
        except OSError:
            raw_name = ""
        if "package" not in raw_name or "core" in raw_name:
            continue
        try:
            uw = int(pw_f.read_text(encoding="utf-8", errors="replace").strip())
        except (OSError, ValueError):
            continue
        if uw <= 0 or uw > 500_000_000:
            continue
        total += uw
        n += 1
    return total if n else None


def energy_observation(gpu: dict[str, Any]) -> dict[str, Any]:
    """Instantaneous energy counters / power for the host (RAPL package + NVIDIA draw when present)."""
    rapl = rapl_package_energy_uj()
    gpu_w: float | None = None
    nv = gpu.get("nvidia") if isinstance(gpu.get("nvidia"), dict) else {}
    if nv.get("available") and isinstance(nv.get("devices"), list):
        s = 0.0
        n = 0
        for d in nv["devices"]:
            if not isinstance(d, dict):
                continue
            pw = d.get("power_draw_w")
            if isinstance(pw, (int, float)):
                s += float(pw)
                n += 1
        if n:
            gpu_w = round(s, 3)
    out: dict[str, Any] = {
        "rapl_package_uj": rapl.get("total_uj"),
        "rapl_available": bool(rapl.get("available")),
        "gpu_power_draw_w_sum": gpu_w,
    }
    if rapl.get("available"):
        puw = rapl_package_power_uw_sum()
        if puw is not None:
            out["rapl_instant_w"] = round(puw / 1_000_000.0, 3)
    if not rapl.get("available") and isinstance(rapl.get("reason"), str):
        out["rapl_reason"] = rapl["reason"]
    return out


def _parse_meminfo_kb(text: str, key: str) -> int | None:
    for line in text.splitlines():
        if line.startswith(key + ":"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1])
    return None


def cpu_usage_percent_sample(interval_s: float = 0.1) -> float | None:
    """
    Host CPU utilization (0–100) from two ``/proc/stat`` samples (Linux).
    Uses the aggregate ``cpu`` line (global busy jiffies / total jiffies).
    Returns ``None`` on non-Linux or read errors.
    """
    if not sys.platform.startswith("linux"):
        return None

    def _agg() -> tuple[int, int] | None:
        try:
            line = Path("/proc/stat").read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except OSError:
            return None
        if not line.startswith("cpu "):
            return None
        parts = line.split()
        try:
            nums = [int(x) for x in parts[1:8]]
        except ValueError:
            return None
        # user nice system idle iowait irq softirq
        idle = nums[3] + nums[4]
        total = sum(nums)
        return idle, total

    a1 = _agg()
    if a1 is None:
        return None
    idle1, total1 = a1
    time.sleep(max(0.02, float(interval_s)))
    a2 = _agg()
    if a2 is None:
        return None
    idle2, total2 = a2
    didle = idle2 - idle1
    dtotal = total2 - total1
    if dtotal <= 0:
        return None
    busy_pct = 100.0 * (1.0 - (didle / dtotal))
    return round(max(0.0, min(100.0, busy_pct)), 1)


def _per_cpu_jiffies_line(line: str) -> tuple[str, int, int] | None:
    parts = line.split()
    if len(parts) < 8:
        return None
    tag = parts[0]
    if tag == "cpu" or not tag.startswith("cpu"):
        return None
    suffix = tag[3:]
    if not suffix.isdigit():
        return None
    try:
        nums = [int(x) for x in parts[1:8]]
    except ValueError:
        return None
    idle = nums[3] + nums[4]
    total = sum(nums)
    return tag, idle, total


def cpu_usage_percent_per_core_avg_sample(interval_s: float = 0.06) -> float | None:
    """
    Average per-logical-CPU busy %% (0–100) from ``cpu0`` … lines in ``/proc/stat``.

    Interprets “half the cores at ~50%% busy” as ~25%% overall — the arithmetic mean
    of each core’s busy%% between two samples. Falls back to the aggregate ``cpu`` line
    if per-CPU lines are missing.
    """
    if not sys.platform.startswith("linux"):
        return None

    def sample() -> dict[str, tuple[int, int]] | None:
        try:
            lines = Path("/proc/stat").read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
        out: dict[str, tuple[int, int]] = {}
        for line in lines:
            row = _per_cpu_jiffies_line(line)
            if row is None:
                continue
            tag, idle, total = row
            out[tag] = (idle, total)
        return out or None

    t1 = sample()
    if not t1:
        return cpu_usage_percent_sample(interval_s)
    time.sleep(max(0.02, float(interval_s)))
    t2 = sample()
    if not t2:
        return None
    pcts: list[float] = []
    for tag, (idle1, total1) in t1.items():
        if tag not in t2:
            continue
        idle2, total2 = t2[tag]
        didle = idle2 - idle1
        dtotal = total2 - total1
        if dtotal <= 0:
            continue
        busy_pct = 100.0 * (1.0 - (didle / dtotal))
        pcts.append(max(0.0, min(100.0, busy_pct)))
    if not pcts:
        return cpu_usage_percent_sample(interval_s)
    return round(sum(pcts) / len(pcts), 1)


def physical_cpu_cores_linux() -> int | None:
    """Count unique physical cores from sysfs ``topology`` (socket + core id)."""
    if not sys.platform.startswith("linux"):
        return None
    root = Path("/sys/devices/system/cpu")
    if not root.is_dir():
        return None
    pairs: set[tuple[int, int]] = set()
    for cpu_dir in sorted(root.glob("cpu[0-9]*")):
        if not cpu_dir.is_dir():
            continue
        pkg_f = cpu_dir / "topology" / "physical_package_id"
        core_f = cpu_dir / "topology" / "core_id"
        if not pkg_f.is_file() or not core_f.is_file():
            continue
        try:
            pkg = int(pkg_f.read_text(encoding="utf-8", errors="replace").strip())
            cid = int(core_f.read_text(encoding="utf-8", errors="replace").strip())
        except (OSError, ValueError):
            continue
        pairs.add((pkg, cid))
    return len(pairs) if pairs else None


def cpufreq_metrics() -> dict[str, Any]:
    """Current clock (avg) and cpufreq governor / EPP when sysfs exposes them."""
    empty: dict[str, Any] = {
        "cpu_freq_mhz_avg": None,
        "cpu_scaling_governor": None,
        "cpu_energy_performance_preference": None,
    }
    if not sys.platform.startswith("linux"):
        return empty
    root = Path("/sys/devices/system/cpu")
    if not root.is_dir():
        return empty
    freqs: list[float] = []
    govs: set[str] = set()
    epps: set[str] = set()
    for cpu_dir in sorted(root.glob("cpu[0-9]*"), key=lambda p: int(p.name[3:])):
        if not cpu_dir.is_dir():
            continue
        cf = cpu_dir / "cpufreq" / "scaling_cur_freq"
        gv = cpu_dir / "cpufreq" / "scaling_governor"
        epp = cpu_dir / "cpufreq" / "energy_performance_preference"
        try:
            if cf.is_file():
                hz = int(cf.read_text(encoding="utf-8", errors="replace").strip())
                freqs.append(hz / 1000.0)
        except (OSError, ValueError):
            pass
        try:
            if gv.is_file():
                govs.add(gv.read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            pass
        try:
            if epp.is_file():
                epps.add(epp.read_text(encoding="utf-8", errors="replace").strip())
        except OSError:
            pass
    out = dict(empty)
    if freqs:
        out["cpu_freq_mhz_avg"] = round(sum(freqs) / len(freqs), 0)
    if len(govs) == 1:
        out["cpu_scaling_governor"] = next(iter(govs))
    elif len(govs) > 1:
        joined = ", ".join(sorted(govs))
        out["cpu_scaling_governor"] = "mixed (" + (joined if len(joined) <= 48 else joined[:45] + "…") + ")"
    if len(epps) == 1:
        out["cpu_energy_performance_preference"] = next(iter(epps))
    elif len(epps) > 1:
        out["cpu_energy_performance_preference"] = "mixed"
    return out


