"""Read-only host metrics (stdlib only; Linux-friendly)."""

from __future__ import annotations

import csv
import io
import os
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


def _uevent_field(uevent_path: Path, key: str) -> str:
    if not uevent_path.is_file():
        return ""
    try:
        for line in uevent_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def amdgpu_sysfs_snapshot() -> dict[str, Any]:
    """AMD GPU rolling utilization via ``gpu_busy_percent`` (AMDKernel driver)."""
    drm = Path("/sys/class/drm")
    if not drm.is_dir():
        return {"available": False, "reason": "no /sys/class/drm"}
    devices: list[dict[str, Any]] = []
    for card in sorted(drm.glob("card[0-9]")):
        if not card.is_dir() or "-" in card.name:
            continue
        busy_f = card / "device" / "gpu_busy_percent"
        if not busy_f.is_file():
            continue
        dev = card / "device"
        driver = _uevent_field(dev / "uevent", "DRIVER").lower() or "unknown"
        try:
            pct = int(busy_f.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        pci = _uevent_field(dev / "uevent", "PCI_SLOT_NAME")
        devices.append(
            {
                "card": card.name,
                "pci_slot": pci,
                "utilization_pct": max(0, min(100, pct)),
                "driver": driver,
            }
        )
    if not devices:
        return {"available": False, "reason": "no DRM gpu_busy_percent sysfs (typical: AMD)"}
    return {"available": True, "backend": "drm-sysfs", "devices": devices}


def _intel_busy_counter_paths() -> list[Path]:
    drm = Path("/sys/class/drm")
    if not drm.is_dir():
        return []
    found: set[Path] = set()
    for pattern in (
        "card[0-9]/engine/*/busy",
        "card[0-9]/gt/gt*/rcs0/busy",
        "card[0-9]/gt/gt*/busy",
    ):
        found.update(drm.glob(pattern))
    return sorted(found, key=lambda p: str(p))


def intel_engine_busy_snapshot() -> dict[str, Any]:
    """
    Intel / Xe DRM: approximate GPU busy%% from engine cumulative busy counters
    (two samples ~120ms apart). Requires accessible sysfs counters (kernel/driver dependent).
    """
    paths = _intel_busy_counter_paths()
    if not paths:
        return {"available": False, "reason": "no DRM engine busy sysfs (Intel/Xe)"}
    try:
        v1 = {p: int(p.read_text(encoding="utf-8").strip()) for p in paths}
    except (OSError, ValueError):
        return {"available": False, "reason": "could not read engine busy counters"}
    t1 = time.perf_counter_ns()
    time.sleep(0.12)
    t2 = time.perf_counter_ns()
    try:
        v2 = {p: int(p.read_text(encoding="utf-8").strip()) for p in paths}
    except (OSError, ValueError):
        return {"available": False, "reason": "could not resample engine busy counters"}
    wall = max(1, t2 - t1)
    by_card: dict[str, list[float]] = {}
    for p in paths:
        parts = p.parts
        try:
            idx = parts.index("drm") + 1
            card = parts[idx]
        except (ValueError, IndexError):
            card = "unknown"
        delta = max(0, v2[p] - v1[p])
        pct = min(100.0, 100.0 * float(delta) / float(wall))
        by_card.setdefault(card, []).append(pct)
    devs: list[dict[str, Any]] = []
    for card in sorted(by_card.keys()):
        raw_max = max(by_card[card])
        devs.append(
            {
                "card": card,
                "utilization_pct_est": round(raw_max, 1),
                "engines_sampled": len(by_card[card]),
            }
        )
    return {
        "available": True,
        "backend": "drm-intel-engine-busy-delta",
        "devices": devs,
        "sample_wall_ms": round(wall / 1_000_000.0, 2),
    }


def rocm_smi_snapshot() -> dict[str, Any]:
    """AMD dGPU/APU via ROCm ``rocm-smi`` when installed."""
    exe = shutil.which("rocm-smi")
    if not exe:
        return {"available": False, "reason": "rocm-smi not in PATH"}
    last_err = ""
    for extra in (["--showuse"], ["-u"], ["--showusage"]):
        try:
            r = subprocess.run([exe, *extra], capture_output=True, text=True, timeout=5.0)
        except (OSError, subprocess.TimeoutExpired) as ex:
            last_err = str(ex)[:200]
            continue
        if r.returncode != 0:
            last_err = (r.stderr or r.stdout or "rocm-smi failed").strip()[:400]
            continue
        text = r.stdout or ""
        devices = _parse_rocm_use(text)
        if devices:
            return {"available": True, "backend": "rocm-smi", "argv": extra, "devices": devices}
        last_err = "no GPU use lines parsed from rocm-smi"
    return {"available": False, "reason": last_err or "rocm-smi produced no utilization"}


def _parse_rocm_use(text: str) -> list[dict[str, Any]]:
    """Parse ``GPU[x] : GPU use (%):`` style lines from ``rocm-smi`` output."""
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(
            r"GPU\[(\d+)\]\s*:\s*GPU use \(\%\):\s*(\d+(?:\.\d+)?)",
            line,
            re.I,
        )
        if m:
            out.append(
                {
                    "index": int(m.group(1)),
                    "utilization_pct": round(min(100.0, max(0.0, float(m.group(2)))), 1),
                }
            )
            continue
        m2 = re.match(
            r"GPU\[(\d+)\]\s*:\s*GPU utilization \(\%\):\s*(\d+(?:\.\d+)?)",
            line,
            re.I,
        )
        if m2:
            out.append(
                {
                    "index": int(m2.group(1)),
                    "utilization_pct": round(min(100.0, max(0.0, float(m2.group(2)))), 1),
                }
            )
    return out


def gpu_bundle() -> dict[str, Any]:
    """Aggregated GPU telemetry from vendor-specific sources."""
    return {
        "nvidia": nvidia_gpu_snapshot(),
        "amdgpu_sysfs": amdgpu_sysfs_snapshot(),
        "intel_drm_est": intel_engine_busy_snapshot(),
        "rocm": rocm_smi_snapshot(),
    }


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


def _diskstats_physical() -> dict[str, tuple[int, int, int]]:
    """Map device name -> (sectors_read, sectors_written, weighted_ms)."""
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
            w_ms = int(parts[13]) if len(parts) > 13 else int(parts[12])
        except (ValueError, IndexError):
            continue
        out[name] = (rsect, wsect, w_ms)
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
        r0, w0, m0 = a[name]
        r1, w1, m1 = b[name]
        dr = max(0, r1 - r0)
        dw = max(0, w1 - w0)
        dm = max(0, m1 - m0)
        read_mbps = (dr * 512) / (1024 * 1024) / dt_s
        write_mbps = (dw * 512) / (1024 * 1024) / dt_s
        busy_pct = min(100.0, max(0.0, 100.0 * dm / wall_ms)) if wall_ms > 0 else None
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
    busy_max = max((d["busy_pct_est"] for d in devices if d.get("busy_pct_est") is not None), default=None)
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
        try:
            up0 = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
            out["system_uptime_s"] = float(up0)
        except (OSError, ValueError, IndexError):
            out["system_uptime_s"] = None
        out["cpu_usage_pct"] = cpu_usage_percent_sample(0.05)
        out["disks"] = {"space": disk_space_snapshot(), "io": disk_io_snapshot()}
    else:
        out["loadavg"] = None
        out["memory"] = None
        out["system_uptime_s"] = None
        out["cpu_usage_pct"] = None
        out["disks"] = {"space": [], "io": {"available": False, "reason": "non-linux"}}
    out["gpu"] = gpu_bundle()
    return out
