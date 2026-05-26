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


def _read_hwmon_millic(path: Path) -> float | None:
    try:
        raw = int(path.read_text(encoding="utf-8", errors="replace").strip())
    except (OSError, ValueError):
        return None
    c = raw / 1000.0
    if -55.0 < c < 200.0:
        return c
    return None


def _amdgpu_hwmon_junction_edge(hdir: Path) -> tuple[float | None, float | None, str]:
    """
    Return (junction_or_hotspot_c, edge_c, detail) for one amdgpu hwmon directory.
    Prefer labeled junction / hotspot / mem junction; else highest temp among non-edge inputs.
    """
    junction: float | None = None
    edge: float | None = None
    generic: list[float] = []
    detail_parts: list[str] = []
    try:
        for tp in sorted(hdir.glob("temp*_input")):
            stem = tp.name[: -len("_input")] if tp.name.endswith("_input") else tp.name
            label_f = hdir / f"{stem}_label"
            lab = ""
            if label_f.is_file():
                try:
                    lab = label_f.read_text(encoding="utf-8", errors="replace").strip().lower()
                except OSError:
                    lab = ""
            t = _read_hwmon_millic(tp)
            if t is None:
                continue
            detail_parts.append(f"{stem}={t:.1f}C({lab or 'n/a'})")
            if lab in ("junction", "hotspot", "tj junction"):
                junction = t if junction is None else max(junction, t)
            elif lab == "edge":
                edge = t if edge is None else max(edge, t)
            elif "junction" in lab or "hotspot" in lab:
                junction = t if junction is None else max(junction, t)
            else:
                generic.append(t)
    except OSError:
        pass
    if junction is None and generic:
        if edge is not None:
            for g in generic:
                if abs(g - edge) > 0.01:
                    junction = g if junction is None else max(junction, g)
        else:
            junction = max(generic)
    if junction is None and edge is not None:
        junction = edge
    det = ",".join(detail_parts[:6]) if detail_parts else "amdgpu"
    return junction, edge, det


def amdgpu_junction_snapshot() -> dict[str, Any]:
    """AMD dGPU junction / hotspot °C from sysfs ``amdgpu`` hwmon under DRM cards."""
    drm = Path("/sys/class/drm")
    if not drm.is_dir():
        return {"available": False, "reason": "no /sys/class/drm"}
    devices: list[dict[str, Any]] = []
    for card in sorted(drm.glob("card[0-9]")):
        if not card.is_dir() or "-" in card.name:
            continue
        dev = card / "device"
        hw_root = dev / "hwmon"
        if not hw_root.is_dir():
            continue
        for hdir in sorted(hw_root.glob("hwmon*")):
            try:
                name = (hdir / "name").read_text(encoding="utf-8", errors="replace").strip().lower()
            except OSError:
                continue
            if name != "amdgpu":
                continue
            junc, edg, det = _amdgpu_hwmon_junction_edge(hdir)
            if junc is None:
                continue
            pci = _uevent_field(dev / "uevent", "PCI_SLOT_NAME")
            rec: dict[str, Any] = {
                "card": card.name,
                "pci_slot": pci,
                "junction_c": round(junc, 1),
                "detail": det[:500],
            }
            if edg is not None:
                rec["edge_c"] = round(edg, 1)
            devices.append(rec)
    if not devices:
        return {"available": False, "reason": "no amdgpu hwmon junction temps"}
    return {"available": True, "backend": "amdgpu-hwmon", "devices": devices}


def linux_soc_junction_rated_sysfs() -> bool:
    """
    True when sysfs exposes a positive crit/trip hint (ARM SoC policy rated junction).

    Used by thermal LLM advisory for ``critical`` tier at 110 °C (ARM SoC band).
    """
    if not sys.platform.startswith("linux"):
        return False
    try:
        hw = Path("/sys/class/hwmon")
        if hw.is_dir():
            for hdir in hw.glob("hwmon*"):
                for crit in hdir.glob("temp*_crit"):
                    try:
                        raw = int(crit.read_text(encoding="utf-8", errors="replace").strip())
                    except (OSError, ValueError):
                        continue
                    if raw > 0:
                        return True
    except OSError:
        pass
    try:
        tz_root = Path("/sys/class/thermal")
        if tz_root.is_dir():
            for zdir in sorted(tz_root.glob("thermal_zone*"), key=lambda p: p.name):
                for name in ("trip_point_0_temp", "trip_point_1_temp", "trip_point_2_temp"):
                    tpf = zdir / name
                    if not tpf.is_file():
                        continue
                    try:
                        raw = int(tpf.read_text(encoding="utf-8", errors="replace").strip())
                    except (OSError, ValueError):
                        continue
                    if raw > 0:
                        return True
    except OSError:
        pass
    return False


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
        "amdgpu_temps": amdgpu_junction_snapshot(),
        "intel_drm_est": intel_engine_busy_snapshot(),
        "rocm": rocm_smi_snapshot(),
    }


