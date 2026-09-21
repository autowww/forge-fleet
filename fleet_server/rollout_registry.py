"""Load declarative service rollout registry."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).with_name("rollout_registry.json")


@dataclass(frozen=True)
class RolloutSpec:
    service_id: str
    script: str
    slot_service_id: str | None = None
    slot_env_param: str | None = None
    default_env: str | None = None
    supports_source_overlay: bool = False
    infra_flow_id: str | None = None
    source_overlay: dict[str, Any] = field(default_factory=dict)
    health_url: str | None = None
    overrides: dict[str, str] = field(default_factory=dict)
    confirm_gates: dict[str, dict[str, str]] = field(default_factory=dict)
    backup: dict[str, Any] = field(default_factory=dict)


def _load_doc() -> dict[str, Any]:
    data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"services": {}}


def list_service_ids() -> list[str]:
    doc = _load_doc()
    services = doc.get("services") or {}
    return sorted(str(k) for k in services.keys())


def get(service_id: str) -> RolloutSpec | None:
    sid = str(service_id or "").strip()
    if not sid:
        return None
    doc = _load_doc()
    services = doc.get("services") or {}
    raw = services.get(sid)
    if not isinstance(raw, dict):
        return None
    script = str(raw.get("script") or "").strip()
    if not script:
        return None
    return RolloutSpec(
        service_id=sid,
        script=script,
        slot_service_id=str(raw.get("slot_service_id") or "").strip() or None,
        slot_env_param=str(raw.get("slot_env_param") or "").strip() or None,
        default_env=str(raw.get("default_env") or "").strip() or None,
        supports_source_overlay=bool(raw.get("supports_source_overlay")),
        infra_flow_id=str(raw.get("infra_flow_id") or "").strip() or None,
        source_overlay=dict(raw.get("source_overlay") or {}),
        health_url=str(raw.get("health_url") or "").strip() or None,
        overrides={str(k): str(v) for k, v in (raw.get("overrides") or {}).items()},
        confirm_gates=dict(raw.get("confirm_gates") or {}),
        backup=dict(raw.get("backup") or {}),
    )


def resolve_slot_service_id(spec: RolloutSpec, body: dict[str, Any]) -> str:
    if spec.slot_service_id:
        return spec.slot_service_id
    return spec.service_id


def apply_overrides(env: dict[str, str], spec: RolloutSpec, body: dict[str, Any]) -> list[str]:
    """Apply registry override map; return unknown keys for rejection."""
    unknown: list[str] = []
    allowed = set(spec.overrides.keys()) | {"sync"}
    for key, val in body.items():
        if key not in allowed and val is not None:
            unknown.append(str(key))
    for src, dst in spec.overrides.items():
        raw = body.get(src)
        if raw is None:
            raw = body.get(dst)
        if raw is None:
            continue
        if dst == "FORGE_MARKET_RUN_SCHEMA_MIGRATE":
            if isinstance(raw, bool):
                env[dst] = "1" if raw else "0"
            else:
                val = str(raw).strip()
                if val.lower() in ("1", "true", "yes", "on"):
                    env[dst] = "1"
                elif val.lower() in ("0", "false", "no", "off"):
                    env[dst] = "0"
                elif val:
                    env[dst] = val
            continue
        if dst in {
            "FORGE_MARKET_PAUSE_SCHEDULER",
            "FORGE_MARKET_SKIP_BUILD",
            "FORGE_MARKET_SKIP_GIT_SYNC",
            "FORGE_MARKET_GIT_HARD_RESET",
            "FORGE_MARKET_SKIP_BACKUP",
        }:
            if isinstance(raw, bool):
                env[dst] = "1" if raw else "0"
            else:
                val = str(raw).strip().lower()
                if val in ("1", "true", "yes", "on"):
                    env[dst] = "1"
                elif val in ("0", "false", "no", "off"):
                    env[dst] = "0"
                elif val:
                    env[dst] = str(raw).strip()
            continue
        val = str(raw).strip()
        if val:
            env[dst] = val
    return unknown


def flow_service_id(flow_id: str) -> str | None:
    doc = _load_doc()
    services = doc.get("services") or {}
    fid = str(flow_id or "").strip()
    for sid, raw in services.items():
        if isinstance(raw, dict) and str(raw.get("infra_flow_id") or "") == fid:
            return str(sid)
    if fid.startswith("market-studio"):
        return "market-studio"
    return None
