"""Catalog-backed candidate shortlist (no auto-promote)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
import time

from runners.base import ArtifactPin
from runners.loader import load_runner_config

ADEQUATE_FITS = frozenset({"candidate", "tight_or_offload"})
# Tasks served by embedding/reranker models, never by a resident chat model.
EMBEDDING_TASKS = frozenset({"embedding", "hybrid", "code_search", "rerank"})


def _looks_like_embedding_model(runner_model_id: str) -> bool:
    s = runner_model_id.lower()
    return "embed" in s or "rerank" in s or "bge-" in s or s.startswith("e5-")


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


def pinned_openai_model_objects(
    existing: list[dict[str, Any]],
    *,
    include_synthetic: bool,
) -> list[dict[str, Any]]:
    """
    When include_synthetic, ensure every enabled artifact pin appears in GET /v1/models
    even if the runner has not pulled the tag yet (Open WebUI catalog UX).
    """
    if not include_synthetic:
        return existing
    pin_ids = [p[0] for p in enabled_pins()]
    if not pin_ids:
        return existing
    by_id = {
        str(m.get("id")): m
        for m in existing
        if isinstance(m, dict) and m.get("id")
    }
    out = list(existing)
    now = int(time.time())
    for mid in pin_ids:
        if mid in by_id:
            continue
        out.append(
            {
                "id": mid,
                "object": "model",
                "created": now,
                "owned_by": "forge-gateway",
            }
        )
    return out


def _runtime_filter(kind: str) -> str | None:
    if kind == "ollama":
        return "llama.cpp"
    if kind == "llama_cpp":
        return "llama.cpp"
    if kind == "vllm":
        return "vLLM"
    return None


def catalog_evidence() -> dict[str, Any]:
    """Catalog provenance stamped on every routed request (README routing step 8)."""
    try:
        catalog = load_catalog()
    except (OSError, ValueError, json.JSONDecodeError, FileNotFoundError):
        return {"catalog_schema": None, "catalog_date": None}
    return {
        "catalog_schema": catalog.get("schema"),
        "catalog_date": catalog.get("date"),
    }


def catalog_candidates_for_task(
    task_id: str,
    *,
    free_vram_gb: float | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    """
    Tier shortlist for a task, filtered by runtime family and (optionally) verified language.

    Mirrors ``forge_llm_selector.select``: models with a non-empty ``verified_languages`` list that
    lacks ``language`` are excluded; models with no allowlist are kept and flagged.
    """
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
    pinned_aliases = {ca for _, ca in enabled_pins() if ca}
    lang = (language or "").strip().lower() or None
    out: list[dict[str, Any]] = []
    for rank, cell in enumerate(tasks[task_id]["candidates_by_vram_gb"].get(str(tier), []), 1):
        alias = cell.get("alias")
        if not alias or alias not in by_alias:
            continue
        m = by_alias[alias]
        if m.get("estimated_min_vram_tier_gb", 999) > vram:
            continue
        flags: list[str] = []
        if runtime and runtime not in (m.get("candidate_runtimes") or []):
            # README step 4: "observed runtime support" beats the catalog's candidate list.
            # An enabled pin for this alias is the operator's observation that the runtime
            # serves it (e.g. Ollama GGUF of an embedding model the catalog lists only for vLLM).
            if alias not in pinned_aliases:
                continue
            flags.append("runtime_support_from_pin_not_catalog")
        verified = [str(x).lower() for x in (m.get("verified_languages") or [])]
        if lang:
            if verified and lang not in verified:
                continue
            if not verified:
                flags.append("language_support_requires_test")
        out.append(
            {
                "rank": rank,
                "alias": alias,
                "fit": cell.get("fit") or "candidate",
                "model_id": m.get("model_id"),
                "flags": flags,
            }
        )
    return out


def measured_fit(pin: ArtifactPin, *, free_vram_gb: float | None = None) -> str:
    """
    Headroom check against a **measured** peak (README routing step 5; ``fit_policy.minimum_host_free_vram_ratio``).

    Returns ``unmeasured`` when no peak was recorded, ``fits_with_headroom`` when
    ``peak * (1 + headroom_ratio) <= free_vram``, else ``exceeds_headroom``.
    """
    cfg = load_runner_config()
    vram_mib = (free_vram_gb if free_vram_gb is not None else cfg.free_vram_gb) * 1024.0
    m = pin.measured
    if m is None or m.peak_vram_mib is None:
        return "unmeasured"
    if float(m.peak_vram_mib) * (1.0 + cfg.headroom_ratio) <= vram_mib:
        return "fits_with_headroom"
    return "exceeds_headroom"


def pin_by_id(runner_model_id: str) -> ArtifactPin | None:
    cfg = load_runner_config()
    for p in cfg.artifact_pins:
        if p.runner_model_id == runner_model_id:
            return p
    return None


def pin_for_alias(alias: str) -> str | None:
    for mid, ca in enabled_pins():
        if ca == alias:
            return mid
    return None


def resolve_runner_model_for_task(
    task_id: str,
    *,
    language: str | None = None,
) -> tuple[str | None, str | None, str]:
    """
    Pick best enabled pin for task. Returns (runner_model_id, catalog_alias, fit).
    fit is candidate|tight_or_offload|low_quality_fallback|legacy|none
    """
    pins = enabled_pins()
    pin_ids = {p[0] for p in pins}
    candidates = catalog_candidates_for_task(task_id, language=language)
    for c in candidates:
        alias = c["alias"]
        fit = str(c.get("fit") or "candidate")
        mid = pin_for_alias(alias)
        if mid:
            pin = pin_by_id(mid)
            if pin is not None and measured_fit(pin) == "exceeds_headroom":
                continue
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
    *,
    language: str | None = None,
) -> tuple[str | None, str | None, str]:
    """If a resident runner model is an adequate catalog fit for task, return it."""
    if not resident_models:
        return None, None, "none"
    resident_set = set(resident_models)
    candidates = catalog_candidates_for_task(task_id, language=language)
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
    # Legacy fallback: a resident pin *without* a catalog alias (not evaluated above) may
    # serve the task when the model kind matches. Pins with an alias were already judged
    # by the catalog and must not be reused for tasks they are not candidates for
    # (e.g. a resident chat model must never answer /v1/embeddings).
    want_embed = task_id in EMBEDDING_TASKS
    for mid, ca in enabled_pins():
        if mid not in resident_set or ca:
            continue
        if _looks_like_embedding_model(mid) == want_embed:
            return mid, ca, "legacy_resident"
    return None, None, "none"
