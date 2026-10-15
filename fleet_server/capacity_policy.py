"""Persisted capacity policy (disk + memory) under data_dir/etc/capacity-policy.json."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fleet_server import space_policy

_POLICY_VERSION = 1
_FILENAME = "capacity-policy.json"


def policy_path(data_dir: Path) -> Path:
    return data_dir / "etc" / _FILENAME


def _default_memory_block() -> dict[str, Any]:
    return {
        "enabled": True,
        "apply_stops": False,
        "cold_idle_hours": 2.0,
        "warm_idle_hours": 6.0,
        "free_ram_floor_gib": 16.0,
        "pinned_service_ids": ["default", "market-studio"],
        "warm_service_ids": ["market-studio-dev"],
        "cold_targets": [
            {"id": "host-ollama", "kind": "systemd_user", "unit": "ollama.service"},
            {"id": "comfyui", "kind": "compose_service", "service_name": "comfyui"},
        ],
    }


def default_policy() -> dict[str, Any]:
    return {
        "version": _POLICY_VERSION,
        "space": {"enabled": None},
        "memory": _default_memory_block(),
    }


def _merge_memory(raw: dict[str, Any]) -> dict[str, Any]:
    out = _default_memory_block()
    if not isinstance(raw, dict):
        return out
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    if "apply_stops" in raw:
        out["apply_stops"] = bool(raw.get("apply_stops"))
    for key in ("cold_idle_hours", "warm_idle_hours", "free_ram_floor_gib"):
        if key in raw:
            try:
                out[key] = float(raw[key])
            except (TypeError, ValueError):
                pass
    if isinstance(raw.get("pinned_service_ids"), list):
        out["pinned_service_ids"] = [str(x).strip() for x in raw["pinned_service_ids"] if str(x).strip()]
    if isinstance(raw.get("warm_service_ids"), list):
        out["warm_service_ids"] = [str(x).strip() for x in raw["warm_service_ids"] if str(x).strip()]
    if isinstance(raw.get("cold_targets"), list):
        cold: list[dict[str, Any]] = []
        for row in raw["cold_targets"]:
            if isinstance(row, dict) and str(row.get("id") or "").strip():
                cold.append(dict(row))
        if cold:
            out["cold_targets"] = cold
    return out


def load_policy(data_dir: Path) -> dict[str, Any]:
    path = policy_path(data_dir)
    if not path.is_file():
        return default_policy()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_policy()
    if not isinstance(doc, dict):
        return default_policy()
    out = default_policy()
    out["version"] = int(doc.get("version") or _POLICY_VERSION)
    space = doc.get("space") if isinstance(doc.get("space"), dict) else {}
    if "enabled" in space:
        en = space.get("enabled")
        out["space"]["enabled"] = None if en is None else bool(en)
    mem = doc.get("memory") if isinstance(doc.get("memory"), dict) else {}
    out["memory"] = _merge_memory(mem)
    return out


def save_policy(data_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    current = load_policy(data_dir)
    if isinstance(patch.get("space"), dict):
        sp = patch["space"]
        if "enabled" in sp:
            en = sp.get("enabled")
            current["space"]["enabled"] = None if en is None else bool(en)
    if isinstance(patch.get("memory"), dict):
        current["memory"] = _merge_memory({**current["memory"], **patch["memory"]})
    path = policy_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return current


def space_loop_enabled(data_dir: Path) -> bool:
    doc = load_policy(data_dir)
    space = doc.get("space") if isinstance(doc.get("space"), dict) else {}
    en = space.get("enabled")
    if en is None:
        return space_policy.guardian_enabled()
    return bool(en)


def memory_loop_enabled(data_dir: Path) -> bool:
    doc = load_policy(data_dir)
    mem = doc.get("memory") if isinstance(doc.get("memory"), dict) else {}
    return bool(mem.get("enabled", True))


def memory_apply_stops(data_dir: Path) -> bool:
    doc = load_policy(data_dir)
    mem = doc.get("memory") if isinstance(doc.get("memory"), dict) else {}
    return bool(mem.get("apply_stops", False))


def memory_free_ram_floor_bytes(data_dir: Path) -> int:
    doc = load_policy(data_dir)
    mem = doc.get("memory") if isinstance(doc.get("memory"), dict) else {}
    try:
        gib = float(mem.get("free_ram_floor_gib") or 16.0)
    except (TypeError, ValueError):
        gib = 16.0
    return int(max(1.0, gib) * 1024**3)


def memory_idle_seconds(data_dir: Path, *, warm: bool) -> float:
    doc = load_policy(data_dir)
    mem = doc.get("memory") if isinstance(doc.get("memory"), dict) else {}
    key = "warm_idle_hours" if warm else "cold_idle_hours"
    try:
        hours = float(mem.get(key) or (6.0 if warm else 2.0))
    except (TypeError, ValueError):
        hours = 6.0 if warm else 2.0
    return max(0.25, hours) * 3600.0


def env_memory_guardian_default() -> bool:
    raw = str(os.environ.get("FLEET_MEMORY_GUARDIAN") or "1").strip().lower()
    return raw not in {"0", "false", "off", "no"}
