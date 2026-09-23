"""Load lifecycle dependent registry and merge rollout health URLs."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fleet_server import rollout_registry

_REGISTRY_PATH = Path(__file__).with_name("lifecycle_registry.json")
_HEALTH_TO_READINESS = re.compile(r"/health/?$", re.I)
_HEALTH_TO_PREPARE = re.compile(r"/health/?$", re.I)


@dataclass(frozen=True)
class LifecycleDependent:
    service_id: str
    prepare_url: str
    readiness_url: str
    optional: bool = True


def _load_static() -> list[LifecycleDependent]:
    if not _REGISTRY_PATH.is_file():
        return []
    try:
        doc = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: list[LifecycleDependent] = []
    for raw in doc.get("dependents") or []:
        if not isinstance(raw, dict):
            continue
        sid = str(raw.get("service_id") or "").strip()
        prep = str(raw.get("prepare_url") or "").strip()
        ready = str(raw.get("readiness_url") or "").strip()
        if not sid or not prep or not ready:
            continue
        out.append(
            LifecycleDependent(
                service_id=sid,
                prepare_url=prep,
                readiness_url=ready,
                optional=bool(raw.get("optional", True)),
            )
        )
    return out


def _from_rollout_registry() -> list[LifecycleDependent]:
    out: list[LifecycleDependent] = []
    for sid in rollout_registry.list_service_ids():
        spec = rollout_registry.get(sid)
        if spec is None or not spec.health_url:
            continue
        health = spec.health_url.rstrip("/")
        base = _HEALTH_TO_READINESS.sub("", health)
        out.append(
            LifecycleDependent(
                service_id=sid,
                prepare_url=f"{base}/api/lifecycle/prepare-stop",
                readiness_url=f"{base}/api/lifecycle/stop-readiness",
                optional=True,
            )
        )
    return out


def _from_env_extra() -> list[LifecycleDependent]:
    raw = str(os.environ.get("FLEET_LIFECYCLE_EXTRA", "") or "").strip()
    if not raw:
        return []
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(doc, list):
        return []
    out: list[LifecycleDependent] = []
    for item in doc:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("service_id") or "").strip()
        prep = str(item.get("prepare_url") or "").strip()
        ready = str(item.get("readiness_url") or "").strip()
        if sid and prep and ready:
            out.append(
                LifecycleDependent(
                    service_id=sid,
                    prepare_url=prep,
                    readiness_url=ready,
                    optional=bool(item.get("optional", True)),
                )
            )
    return out


def list_dependents() -> list[LifecycleDependent]:
    merged: dict[str, LifecycleDependent] = {}
    for dep in _from_rollout_registry():
        merged[dep.service_id] = dep
    for dep in _load_static():
        merged[dep.service_id] = dep
    for dep in _from_env_extra():
        merged[dep.service_id] = dep
    return sorted(merged.values(), key=lambda d: d.service_id)
