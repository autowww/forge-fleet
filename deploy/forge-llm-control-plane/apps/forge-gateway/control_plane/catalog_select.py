"""Catalog-backed candidate shortlist (no auto-promote)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runners.loader import load_runner_config

ADEQUATE_FITS = frozenset({"candidate", "tight_or_offload"})


@lru_cache(maxsize=4)
def load_catalog(path: str | None = None) -> dict[str, Any]:
    cfg = load_runner_config()
    cat_path = path or cfg.catalog_path
    if not cat_path:
        bundled = (
            Path(__file__).resolve().parents[3] / "configs" / "catalog" / "forge_llm_catalog_2026-11-03.json"
        )
        cat_path = str(bundled) if bundled.is_file() else None
    if not cat_path:
        raise FileNotFoundError("catalog_path not configured")
    return json.loads(Path(cat_path).read_text(encoding="utf-8"))


def enabled_pins() -> list[tuple[str, str | None]]:
    """(runner_model_id, catalog_alias) for enabled pins."""
    cfg = load_runner_config()
    if cfg.artifact_pins:
        return [(p.runner_model_id, p.catalog_alias) for p in cfg.artifact_pins if p.enabled]
    return [(m, None) for m in cfg.models]


def _runtime_filter(kind: str) -> str | None:
    if kind == "ollama":
        return "llama.cpp"
    if kind == "llama_cpp":
        return "llama.cpp"
    if kind == "vllm":
        return "vLLM"
    return None


def catalog_candidates_for_task(
    task_id: str,
    *,
    free_vram_gb: float | None = None,
) -> list[dict[str, Any]]:
    cfg = load_runner_config()
    vram = free_vram_gb if free_vram_gb is not None else cfg.free_vram_gb
    try:
        catalog = load_catalog()
    except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError):
        return []
    tiers = [t for t in catalog.get("vram_tiers_gb", []) if t <= vram]
    if not tiers:
        return []
    tier = max(tiers)
    tasks = {r["task_id"]: r for r in catalog.get("tasks", [])}
    if task_id not in tasks:
        return []
    by_alias = {m["alias"]: m for m in catalog.get("models", [])}
    runtime = _runtime_filter(cfg.kind)
    out: list[dict[str, Any]] = []
    for rank, cell in enumerate(tasks[task_id]["candidates_by_vram_gb"].get(str(tier), []), 1):
        alias = cell.get("alias")
        if not alias or alias not in by_alias:
            continue
        m = by_alias[alias]
        if m.get("estimated_min_vram_tier_gb", 999) > vram:
            continue
        if runtime and runtime not in (m.get("candidate_runtimes") or []):
            continue
        out.append(
            {
                "rank": rank,
                "alias": alias,
                "fit": cell.get("fit") or "candidate",
                "model_id": m.get("model_id"),
            }
        )
    return out


def pin_for_alias(alias: str) -> str | None:
    for mid, ca in enabled_pins():
        if ca == alias:
            return mid
    return None


def resolve_runner_model_for_task(task_id: str) -> tuple[str | None, str | None, str]:
    """
    Pick best enabled pin for task. Returns (runner_model_id, catalog_alias, fit).
    fit is candidate|tight_or_offload|low_quality_fallback|legacy|none
    """
    pins = enabled_pins()
    pin_ids = {p[0] for p in pins}
    candidates = catalog_candidates_for_task(task_id)
    for c in candidates:
        alias = c["alias"]
        fit = str(c.get("fit") or "candidate")
        mid = pin_for_alias(alias)
        if mid:
            return mid, alias, fit
    if task_id == "embedding":
        for mid, _ in pins:
            if "embed" in mid.lower() or "nomic" in mid.lower():
                return mid, None, "legacy"
    cfg = load_runner_config()
    from control_plane.task_resolve import TASK_TO_MODE

    mode = TASK_TO_MODE.get(task_id, "interactive")
    legacy = cfg.mode_models.get(mode)
    if legacy and legacy in pin_ids:
        return legacy, None, "legacy"
    if legacy:
        return legacy, None, "legacy"
    if pins:
        return pins[0][0], pins[0][1], "legacy"
    return None, None, "none"


def resident_adequate_pin(
    task_id: str,
    resident_models: list[str],
) -> tuple[str | None, str | None, str]:
    """If a resident runner model is an adequate catalog fit for task, return it."""
    if not resident_models:
        return None, None, "none"
    resident_set = set(resident_models)
    candidates = catalog_candidates_for_task(task_id)
    alias_by_fit: dict[str, str] = {}
    for c in candidates:
        fit = str(c.get("fit") or "candidate")
        if fit not in ADEQUATE_FITS:
            continue
        alias_by_fit[c["alias"]] = fit
    for mid, ca in enabled_pins():
        if mid not in resident_set:
            continue
        if ca and ca in alias_by_fit:
            return mid, ca, alias_by_fit[ca]
    cfg = load_runner_config()
    for mid, ca in enabled_pins():
        if mid in resident_set:
            return mid, ca, "legacy_resident"
    for rm in resident_models:
        if rm in {p[0] for p in enabled_pins()}:
            return rm, None, "legacy_resident"
    return None, None, "none"
