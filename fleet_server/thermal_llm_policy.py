"""
Thermal LLM advisory: tier thresholds and recommended poll/sleep seconds.

Policy table matches product defaults (see README / admin snapshot ``thermal_llm_advisory``).
Bump ``POLICY_VERSION`` when changing thresholds or semantics.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from typing import Any, Literal

POLICY_VERSION = "2026-05-thermal-v1"

Tier = Literal["ok", "warning", "throttle", "critical"]

_TIER_ORDER: dict[str, int] = {"ok": 0, "warning": 1, "throttle": 2, "critical": 3}


@dataclass(frozen=True)
class Band:
    warning_c: float
    throttle_c: float
    critical_c: float


BAND_INTEL_CPU = Band(90.0, 95.0, 100.0)
BAND_AMD_CPU = Band(85.0, 90.0, 95.0)
BAND_NVIDIA_GPU = Band(78.0, 83.0, 88.0)
BAND_AMD_GPU_HOTSPOT = Band(95.0, 105.0, 110.0)
BAND_ARM_SOC = Band(75.0, 85.0, 105.0)


def _float_env(name: str, default: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def sleep_seconds_for_tier(tier: Tier) -> float:
    if tier == "ok":
        return max(1.0, _float_env("FLEET_THERMAL_SLEEP_OK_S", 3.0))
    if tier == "warning":
        return max(1.0, _float_env("FLEET_THERMAL_SLEEP_WARNING_S", 15.0))
    if tier == "throttle":
        return max(1.0, _float_env("FLEET_THERMAL_SLEEP_THROTTLE_S", 45.0))
    return max(1.0, _float_env("FLEET_THERMAL_SLEEP_CRITICAL_S", 120.0))


def classify_temp_c(temp_c: float, band: Band, *, cap_critical: bool) -> Tier:
    """Classify ``temp_c`` against ``band``. If ``cap_critical``, never return ``critical`` (use ``throttle`` at critical boundary)."""
    if temp_c < band.warning_c:
        return "ok"
    if temp_c < band.throttle_c:
        return "warning"
    if temp_c < band.critical_c:
        return "throttle"
    if cap_critical:
        return "throttle"
    return "critical"


def _parse_cpu_vendor_linux() -> str:
    """Return ``intel`` | ``amd`` | ``arm`` | ``unknown`` from ``/proc/cpuinfo``."""
    try:
        text = open("/proc/cpuinfo", encoding="utf-8", errors="replace").read()
    except OSError:
        return "unknown"
    m = re.search(r"^vendor_id\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    if m:
        v = m.group(1).strip()
        if "intel" in v.lower():
            return "intel"
        if "amd" in v.lower():
            return "amd"
    if re.search(r"^CPU implementer\s*:\s*0x41\b", text, re.MULTILINE):
        return "arm"
    return "unknown"


def _cpu_default_from_env() -> str:
    raw = str(os.environ.get("FLEET_THERMAL_CPU_DEFAULT") or "").strip().lower()
    if raw in ("intel", "amd"):
        return raw
    return "intel"


def resolve_cpu_vendor(host_snap: dict[str, Any]) -> str:
    """Resolve x86/ARM CPU vendor for policy row selection."""
    mach = (host_snap.get("machine") or platform.machine() or "").strip().lower()
    if mach in ("aarch64", "arm64", "armv8l", "armv7l"):
        return "arm"
    if mach in ("x86_64", "amd64", "i386", "i686"):
        th = host_snap.get("thermal")
        src = ""
        if isinstance(th, dict):
            src = str(th.get("source") or "").lower()
        if "k10temp" in src or "zenpower" in src:
            return "amd"
        if "coretemp" in src:
            return "intel"
        v = _parse_cpu_vendor_linux()
        if v in ("intel", "amd"):
            return v
        return _cpu_default_from_env()
    v2 = _parse_cpu_vendor_linux()
    if v2 in ("intel", "amd", "arm"):
        return v2
    return _cpu_default_from_env()


def arm_soc_rated(host_snap: dict[str, Any]) -> bool:
    """ARM SoC critical (105) applies only when junction is considered rated."""
    if _truthy_env("FLEET_ARM_SOC_JUNCTION_RATED"):
        return True
    raw = str(os.environ.get("FLEET_ARM_SOC_TJMAX_C") or "").strip()
    if raw:
        try:
            if float(raw) > 0:
                return True
        except ValueError:
            pass
    th = host_snap.get("thermal")
    if isinstance(th, dict) and th.get("arm_junction_rated") is True:
        return True
    return False


def _thermal_band_for_cpu(vendor: str) -> Band:
    if vendor == "amd":
        return BAND_AMD_CPU
    if vendor == "arm":
        return BAND_ARM_SOC
    return BAND_INTEL_CPU


def _tier_ge(a: Tier, b: Tier) -> bool:
    return _TIER_ORDER[a] >= _TIER_ORDER[b]


def worst_tier(tiers: list[Tier]) -> Tier:
    out: Tier = "ok"
    for t in tiers:
        if _TIER_ORDER[t] > _TIER_ORDER[out]:
            out = t
    return out


def build(host_snap: dict[str, Any]) -> dict[str, Any]:
    """
    Build advisory dict from ``host_stats.snapshot()``-shaped ``host_snap``.

    Expects optional ``host_snap["machine"]`` (else uses ``platform.machine()``).
    """
    # Ensure machine is present for ARM vs x86 without mutating caller dict requirement
    snap = dict(host_snap) if isinstance(host_snap, dict) else {}
    if "machine" not in snap or not snap.get("machine"):
        snap["machine"] = platform.machine()

    vendor = resolve_cpu_vendor(snap)
    cpu_band = _thermal_band_for_cpu(vendor)
    arm_rated = arm_soc_rated(snap) if vendor == "arm" else True
    cap_arm_crit = vendor == "arm" and not arm_rated

    components: list[dict[str, Any]] = []
    tiers: list[Tier] = []

    th = snap.get("thermal")
    cpu_temp: float | None = None
    if isinstance(th, dict):
        mc = th.get("max_c")
        if isinstance(mc, (int, float)) and mc == mc:
            t = float(mc)
            if -80.0 < t < 200.0:
                cpu_temp = t
    if cpu_temp is not None:
        tid = "cpu"
        kind = f"cpu_{vendor}"
        tier = classify_temp_c(cpu_temp, cpu_band, cap_critical=cap_arm_crit)
        components.append(
            {
                "id": tid,
                "kind": kind,
                "temp_c": round(cpu_temp, 2),
                "tier": tier,
                "thresholds_c": {
                    "warning": cpu_band.warning_c,
                    "throttle": cpu_band.throttle_c,
                    "critical": cpu_band.critical_c,
                },
                "sleep_s": round(sleep_seconds_for_tier(tier), 3),
                "detail": f"CPU policy row ({vendor})",
            }
        )
        tiers.append(tier)

    gpu = snap.get("gpu")
    if isinstance(gpu, dict):
        nv = gpu.get("nvidia")
        if isinstance(nv, dict) and nv.get("available") and isinstance(nv.get("devices"), list):
            for i, d in enumerate(nv["devices"]):
                if not isinstance(d, dict):
                    continue
                tc = d.get("temperature_c")
                if not isinstance(tc, (int, float)) or tc != tc:
                    continue
                t = float(tc)
                if not (-80.0 < t < 200.0):
                    continue
                tier = classify_temp_c(t, BAND_NVIDIA_GPU, cap_critical=False)
                components.append(
                    {
                        "id": f"nvidia_gpu_{i}",
                        "kind": "nvidia_gpu_core",
                        "temp_c": round(t, 2),
                        "tier": tier,
                        "thresholds_c": {
                            "warning": BAND_NVIDIA_GPU.warning_c,
                            "throttle": BAND_NVIDIA_GPU.throttle_c,
                            "critical": BAND_NVIDIA_GPU.critical_c,
                        },
                        "sleep_s": round(sleep_seconds_for_tier(tier), 3),
                        "detail": str(d.get("name") or "NVIDIA GPU"),
                    }
                )
                tiers.append(tier)

        aj = gpu.get("amdgpu_temps")
        if isinstance(aj, dict) and aj.get("available") and isinstance(aj.get("devices"), list):
            for i, d in enumerate(aj["devices"]):
                if not isinstance(d, dict):
                    continue
                jc = d.get("junction_c")
                if not isinstance(jc, (int, float)) or jc != jc:
                    continue
                t = float(jc)
                if not (-80.0 < t < 200.0):
                    continue
                tier = classify_temp_c(t, BAND_AMD_GPU_HOTSPOT, cap_critical=False)
                components.append(
                    {
                        "id": f"amd_gpu_hotspot_{i}",
                        "kind": "amd_gpu_hotspot",
                        "temp_c": round(t, 2),
                        "tier": tier,
                        "thresholds_c": {
                            "warning": BAND_AMD_GPU_HOTSPOT.warning_c,
                            "throttle": BAND_AMD_GPU_HOTSPOT.throttle_c,
                            "critical": BAND_AMD_GPU_HOTSPOT.critical_c,
                        },
                        "sleep_s": round(sleep_seconds_for_tier(tier), 3),
                        "detail": str(d.get("card") or f"card{i}"),
                    }
                )
                tiers.append(tier)

    wt = worst_tier(tiers) if tiers else "ok"
    rec_sleep = sleep_seconds_for_tier(wt)

    warn_thresholds: list[float] = []
    for c in components:
        thr = c.get("thresholds_c")
        if isinstance(thr, dict) and "warning" in thr:
            try:
                warn_thresholds.append(float(thr["warning"]))
            except (TypeError, ValueError):
                pass
    startup_max_temp_c: float | None = None
    if warn_thresholds:
        startup_max_temp_c = round(min(warn_thresholds), 1)

    startup_ready = not _tier_ge(wt, "throttle")

    return {
        "policy_version": POLICY_VERSION,
        "cpu_vendor_resolved": vendor,
        "arm_junction_rated": bool(arm_rated) if vendor == "arm" else None,
        "arm_critical_suppressed": bool(cap_arm_crit),
        "components": components,
        "worst_tier": wt,
        "recommended_sleep_s": round(rec_sleep, 3),
        "startup_max_temp_c": startup_max_temp_c,
        "startup_ready": startup_ready,
    }
