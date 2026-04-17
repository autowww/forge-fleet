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
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
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
        pdraw: float | None = None
        if len(row) >= 7:
            ps = (row[6] or "").strip()
            if ps and ps not in ("[N/A]", "N/A"):
                try:
                    pdraw = float(ps)
                except ValueError:
                    pdraw = None
        mem_pct: float | None = None
        if mem_u is not None and mem_t is not None and mem_t > 0:
            mem_pct = round(100.0 * mem_u / mem_t, 1)
        dev: dict[str, Any] = {
            "index": idx,
            "name": name,
            "utilization_pct": util,
            "memory_used_mib": mem_u,
            "memory_total_mib": mem_t,
            "memory_used_pct": mem_pct,
            "temperature_c": temp,
        }
        if pdraw is not None:
            dev["power_draw_w"] = round(pdraw, 2)
        devices.append(dev)
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
        return {"max_c": None, "source": "unavailable", "reason": "no thermal sysfs"}
    best = max(readings, key=lambda t: t[0])
    return {"max_c": round(best[0], 1), "source": best[1]}


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
