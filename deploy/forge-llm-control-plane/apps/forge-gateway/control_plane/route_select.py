"""End-to-end model and lane selection for a request."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from control_plane.catalog_select import (
    ADEQUATE_FITS,
    catalog_candidates_for_task,
    enabled_pins,
    pin_for_alias,
    resident_adequate_pin,
    resolve_runner_model_for_task,
)


def pinned_models_only() -> bool:
    """Production posture (catalog README step 3): only pinned artifacts may be served."""
    return os.environ.get("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
from control_plane.context import ConsumerClass, ForgeContext
from control_plane.external_lane import external_model_for_task, is_external_model
from control_plane.residency import resident_models
from control_plane.task_resolve import TaskResolution, assert_task_supported
from runners.loader import load_runner_config

Lane = Literal["local", "external"]

# Model ids that mean "let the gateway choose from the catalog" (not an explicit pin).
AUTO_MODEL_ALIASES = frozenset({"forge-llm", "forge-llm-auto", "auto", "forge-auto", ""})


@dataclass(frozen=True)
class RoutePlan:
    task: TaskResolution
    lane: Lane
    model: str
    catalog_alias: str | None
    fit: str
    mode_source: str


def _explicit_model(body: dict[str, Any], ctx: ForgeContext) -> str | None:
    h = getattr(ctx, "requested_model", None)
    if h and str(h).strip().lower() not in AUTO_MODEL_ALIASES:
        return str(h).strip()
    raw = body.get("model")
    if isinstance(raw, str) and raw.strip():
        s = raw.strip()
        # Open WebUI may forward its connection prefix (``forge-llm.<id>``); strip it.
        if s.startswith("forge-llm."):
            s = s[len("forge-llm.") :]
        if s.lower() in AUTO_MODEL_ALIASES:
            return None
        return s
    return None


async def plan_route(
    *,
    task: TaskResolution,
    body: dict[str, Any],
    ctx: ForgeContext,
) -> RoutePlan:
    assert_task_supported(task.task_id)
    cfg = load_runner_config()
    pin_ids = {p[0] for p in enabled_pins()}
    explicit = _explicit_model(body, ctx)
    if explicit:
        if explicit in cfg.quarantined_models:
            raise ValueError(f"Model quarantined: {explicit}")
        if is_external_model(explicit):
            if ctx.consumer_class == "local":
                raise ValueError("external models are not allowed for consumer_class=local")
            return RoutePlan(task, "external", explicit, None, "explicit", task.source)
        if explicit in pin_ids or explicit in cfg.models:
            return RoutePlan(task, "local", explicit, None, "explicit", task.source)
        if pinned_models_only():
            raise ValueError(f"model_not_pinned: {explicit!r} is not an enabled artifact pin on this host")
        # Dev/lab posture: honor the caller's model instead of silently substituting.
        return RoutePlan(task, "local", explicit, None, "explicit_unpinned", task.source)

    lang = ctx.language
    residents = await resident_models()
    r_mid, r_alias, r_fit = resident_adequate_pin(task.task_id, residents, language=lang)
    if r_mid and (r_fit in ADEQUATE_FITS or r_fit == "legacy_resident"):
        return RoutePlan(task, "local", r_mid, r_alias, r_fit, task.source)

    best_mid, best_alias, fit = resolve_runner_model_for_task(task.task_id, language=lang)

    candidates = catalog_candidates_for_task(task.task_id, language=lang)
    has_adequate_pin = any(
        str(c.get("fit") or "") in ADEQUATE_FITS and pin_for_alias(str(c.get("alias") or ""))
        for c in candidates
    )

    if ctx.consumer_class == "remote":
        if not has_adequate_pin and not residents:
            ext = external_model_for_task(task.task_id)
            return RoutePlan(task, "external", ext, None, "remote_escalation", task.source)
        if fit == "low_quality_fallback" and not residents:
            ext = external_model_for_task(task.task_id)
            return RoutePlan(task, "external", ext, None, "remote_escalation", task.source)

    if best_mid:
        return RoutePlan(task, "local", best_mid, best_alias, fit, task.source)

    if ctx.consumer_class == "remote":
        ext = external_model_for_task(task.task_id)
        return RoutePlan(task, "external", ext, None, "remote_escalation", task.source)

    raise ValueError("no local model pin configured for task")


def header_task_from_request(headers: dict[str, str]) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    return (h.get("x-forge-task") or "").strip() or None


def header_model_from_request(headers: dict[str, str]) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    return (h.get("x-forge-model") or "").strip() or None
