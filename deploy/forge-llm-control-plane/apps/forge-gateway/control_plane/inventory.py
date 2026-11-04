"""Host catalog inventory: pins, VRAM tier, task routing, runner install state."""

from __future__ import annotations

import os
import time
from typing import Any

from control_plane.catalog_select import (
    ADEQUATE_FITS,
    catalog_candidates_for_task,
    load_catalog,
    measured_fit,
    resolve_runner_model_for_task,
    resident_adequate_pin,
)
from control_plane.config import MAX_QUEUE_DEPTH, QUARANTINED_MODELS
from control_plane.task_resolve import DETERMINISTIC_FIRST_TASKS, UNSUPPORTED_TASK_IDS
from runners.factory import get_adapter
from runners.loader import config_hash, load_runner_config


def _expose_pinned_only() -> bool:
    return os.environ.get("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _nominal_vram_tier_gb(free_vram_gb: float, catalog: dict[str, Any]) -> float | None:
    tiers = [t for t in catalog.get("vram_tiers_gb", []) if t <= free_vram_gb]
    if not tiers:
        return None
    return float(max(tiers))


def _catalog_alias_fit_at_tier(alias: str, free_vram_gb: float, catalog: dict[str, Any]) -> str | None:
    tier = _nominal_vram_tier_gb(free_vram_gb, catalog)
    if tier is None:
        return None
    by_alias = {m["alias"]: m for m in catalog.get("models", [])}
    m = by_alias.get(alias)
    if not m:
        return None
    est = m.get("estimated_min_vram_tier_gb")
    if est is not None and float(est) > free_vram_gb:
        return "exceeds_free_vram"
    tasks = catalog.get("tasks") or []
    best: str | None = None
    for task in tasks:
        if not isinstance(task, dict):
            continue
        tier_key = str(int(tier)) if float(tier) == int(float(tier)) else str(tier)
        cells = (task.get("candidates_by_vram_gb") or {}).get(tier_key, [])
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            if cell.get("alias") != alias:
                continue
            fit = str(cell.get("fit") or "candidate")
            if best is None or fit in ADEQUATE_FITS:
                best = fit
    return best


async def build_catalog_inventory() -> dict[str, Any]:
    cfg = load_runner_config()
    adapter = get_adapter(cfg)
    installed: list[str] = []
    resident: list[str] = []
    runner_error: str | None = None
    try:
        installed = await adapter.list_models()
    except Exception as exc:  # noqa: BLE001
        runner_error = f"list_models: {exc}"[:240]
    try:
        resident = await adapter.resident_models()
    except Exception as exc:  # noqa: BLE001
        if not runner_error:
            runner_error = f"resident_models: {exc}"[:240]

    installed_set = set(installed)
    resident_set = set(resident)
    catalog: dict[str, Any] | None = None
    catalog_error: str | None = None
    try:
        catalog = load_catalog()
    except (OSError, ValueError, TypeError) as exc:
        catalog_error = str(exc)[:240]

    nominal_tier = _nominal_vram_tier_gb(cfg.free_vram_gb, catalog) if catalog else None

    pin_rows: list[dict[str, Any]] = []
    missing_pins: list[str] = []
    for p in cfg.artifact_pins:
        if not p.enabled:
            continue
        missing = p.promotion_missing()
        row: dict[str, Any] = {
            "runner_model_id": p.runner_model_id,
            "catalog_alias": p.catalog_alias,
            "installed": p.runner_model_id in installed_set,
            "resident": p.runner_model_id in resident_set,
            "precision": p.precision,
            "model_revision": p.model_revision,
            "weight_file_sha256": p.weight_file_sha256,
            "runtime_probe": p.runtime_probe,
            "license_approval": p.license_approval,
            "tier_note": p.tier_note,
            "measured_fit": measured_fit(p),
            "promotion": {
                "deployment_authorized": p.deployment_authorized,
                "missing_metrics": missing,
            },
        }
        if p.measured is not None:
            row["measured"] = {
                "peak_vram_mib": p.measured.peak_vram_mib,
                "context_length": p.measured.context_length,
                "active_requests": p.measured.active_requests,
                "p95_latency_ms": p.measured.p95_latency_ms,
                "decode_tokens_per_second": p.measured.decode_tokens_per_second,
                "task_quality_score": p.measured.task_quality_score,
                "runtime_version": p.measured.runtime_version,
                "gpu_uuid": p.measured.gpu_uuid,
            }
        if p.catalog_alias and catalog:
            row["catalog_fit_hint"] = _catalog_alias_fit_at_tier(
                p.catalog_alias, cfg.free_vram_gb, catalog
            )
        elif catalog:
            row["catalog_fit_hint"] = "not_in_catalog"
        pin_rows.append(row)
        if p.runner_model_id not in installed_set:
            missing_pins.append(p.runner_model_id)

    exposed: list[str]
    if _expose_pinned_only():
        exposed = [p.runner_model_id for p in cfg.artifact_pins if p.enabled]
    else:
        pin_ids = {p.runner_model_id for p in cfg.artifact_pins if p.enabled}
        exposed = sorted(installed_set | pin_ids | set(cfg.models))

    task_rows: list[dict[str, Any]] = []
    if catalog:
        for task in catalog.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("task_id") or "")
            if not task_id or task_id in UNSUPPORTED_TASK_IDS:
                continue
            mid, alias, fit = resolve_runner_model_for_task(task_id)
            res_mid, res_alias, res_fit = resident_adequate_pin(task_id, resident)
            candidates = catalog_candidates_for_task(task_id)[:5]
            task_rows.append(
                {
                    "task_id": task_id,
                    "resolved_pin": mid,
                    "catalog_alias": alias,
                    "resolve_fit": fit,
                    "resident_pin": res_mid,
                    "resident_catalog_alias": res_alias,
                    "resident_fit": res_fit,
                    "catalog_candidates": candidates,
                }
            )

    out: dict[str, Any] = {
        "schema": "forge-llm-catalog-v1",
        "generated_ts": time.time(),
        "runner": {
            "kind": cfg.kind,
            "bind": cfg.bind,
            "free_vram_gb": cfg.free_vram_gb,
            "nominal_vram_tier_gb": nominal_tier,
            "catalog_path": cfg.catalog_path,
            "config_hash": config_hash(cfg),
            "classifier_model": cfg.classifier_model,
            "expose_pinned_models_only": _expose_pinned_only(),
            "source_path": cfg.source_path,
        },
        "policy": {
            "max_active_requests": cfg.max_active_requests,
            "max_queue_depth": cfg.max_queue_depth or MAX_QUEUE_DEPTH,
            "headroom_ratio": cfg.headroom_ratio,
            "coalesce_sec": cfg.coalesce_sec,
            "starve_sec": cfg.starve_sec,
            "deterministic_first_tasks": sorted(DETERMINISTIC_FIRST_TASKS),
            "production_policy": (
                "DENY promotion until pinned artifact has measured peak VRAM, runtime probe, "
                "quality score and license approval (catalog fit_policy)"
            ),
        },
        "artifact_pins": pin_rows,
        "deployment_authorized_pins": [
            p.runner_model_id for p in cfg.artifact_pins if p.enabled and p.deployment_authorized
        ],
        "missing_pins": missing_pins,
        "installed_runner_models": installed,
        "resident_models": resident,
        "gateway_exposed_model_ids": exposed,
        "quarantined_models": sorted(QUARANTINED_MODELS | set(cfg.quarantined_models)),
        "tasks": task_rows,
    }
    if catalog_error:
        out["catalog_error"] = catalog_error
    if runner_error:
        out["runner_error"] = runner_error
    if catalog and nominal_tier is not None:
        out["catalog_meta"] = {
            "schema": catalog.get("schema"),
            "date": catalog.get("date"),
            "purpose": catalog.get("purpose"),
            "vram_tiers_gb": catalog.get("vram_tiers_gb"),
            "fit_policy": catalog.get("fit_policy"),
            "metrics_required_for_promotion": catalog.get("metrics_required_for_promotion"),
        }
    return out
