"""Disk-space policy tiers and env knobs for Space Guardian."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def guardian_enabled() -> bool:
    raw = str(os.environ.get("FLEET_SPACE_GUARDIAN") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def interval_s() -> float:
    try:
        return max(300.0, float(os.environ.get("FLEET_SPACE_INTERVAL_S") or "21600"))
    except ValueError:
        return 21600.0


def pressure_free_pct() -> float:
    try:
        return max(1.0, min(50.0, float(os.environ.get("FLEET_SPACE_PRESSURE_FREE_PCT") or "15")))
    except ValueError:
        return 15.0


def pressure_free_gb() -> float:
    try:
        return max(1.0, float(os.environ.get("FLEET_SPACE_PRESSURE_FREE_GB") or "40"))
    except ValueError:
        return 40.0


def volume_quarantine_days() -> int:
    try:
        return max(1, int(os.environ.get("FLEET_VOLUME_QUARANTINE_DAYS") or "14"))
    except ValueError:
        return 14


def volume_snapshot_max_gb() -> float:
    try:
        return max(1.0, float(os.environ.get("FLEET_VOLUME_SNAPSHOT_MAX_GB") or "10"))
    except ValueError:
        return 10.0


def legacy_backup_roots() -> list[Path]:
    raw = str(os.environ.get("FLEET_LEGACY_BACKUP_ROOTS") or "").strip()
    paths: list[Path] = []
    if raw:
        for part in raw.split(":"):
            p = part.strip()
            if p:
                paths.append(Path(p).expanduser())
    home_backups = Path.home() / "forge-market-backups"
    if home_backups.is_dir() and home_backups not in paths:
        paths.append(home_backups)
    return paths


def tier0_cleanup_targets() -> dict[str, Any]:
    """Always-safe targets for scheduled Tier 0 runs."""
    return {
        "rollout_backups": {
            "keep_count": int(os.environ.get("FLEET_ROLLOUT_BACKUP_KEEP_COUNT") or "3"),
            "strict_keep_count": True,
        },
        "migration_scratch": {},
        "job_workspaces": {"max_age_days": 7},
        "docker_builder": {"until_hours": 168},
        "docker_images": {"prune_dangling": True, "until_hours": 168, "prune_unused_all": False},
    }


def tier1_cleanup_targets() -> dict[str, Any]:
    """Pressure-only targets (Tier 1)."""
    return {
        "docker_images_unused": {"until_hours": 72},
        "legacy_backup_roots": {"keep_count": 1},
        "quarantined_volumes": {},
        "app_gc": {"aggressive": True},
    }


def tier_labels() -> dict[int, str]:
    return {
        0: "scheduled_safe",
        1: "pressure_escalation",
        2: "manual_only",
    }
