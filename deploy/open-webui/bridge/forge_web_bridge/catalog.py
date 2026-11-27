"""Open WebUI model ids: base account + optional web UI variant."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any


def _catalog_path() -> Path:
    env = (os.getenv("FORGE_WEB_BRIDGE_MODEL_CATALOG") or "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "config" / "web-model-catalog.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, list[dict[str, Any]]]:
    path = _catalog_path()
    if not path.is_file():
        return {"chatgpt": [], "gemini": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for key in ("chatgpt", "gemini"):
        rows = data.get(key) or []
        out[key] = [r for r in rows if isinstance(r, dict) and r.get("slug")]
    return out


def expose_catalog() -> bool:
    return (os.getenv("FORGE_WEB_BRIDGE_EXPOSE_CATALOG") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def variant_model_id(base_id: str, slug: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(slug).strip()).strip("-")
    return f"{base_id}.{slug}"


def parse_requested_model(requested: str | None, base_id: str) -> tuple[str, dict[str, Any] | None]:
    """Return (openai_model_id, catalog_row or None for session default)."""
    mid = (requested or base_id).strip() or base_id
    if mid == base_id:
        return mid, None
    prefix = f"{base_id}."
    if not mid.startswith(prefix):
        return mid, None
    slug = mid[len(prefix) :].strip()
    if not slug:
        return base_id, None
    provider_rows = []  # filled by caller
    return mid, {"slug": slug, "_lookup": slug}


def catalog_row_for_slug(provider: str, slug: str) -> dict[str, Any] | None:
    for row in load_catalog().get(provider) or []:
        if str(row.get("slug") or "").strip() == slug:
            return row
    return None


def _credits(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for key in ("input", "cached_input", "output", "output_step"):
        if raw.get(key) is None:
            continue
        number = float(raw[key])
        out[key] = int(number) if number.is_integer() else number
    return out or None


def _choice(
    *,
    ids: list[str],
    label: str,
    match: list[str],
    slug: str,
    effort_kind: str | None = None,
    effort_id: str | None = None,
    position: float | None = None,
    credits: dict[str, float] | None = None,
) -> dict[str, Any]:
    cleaned = [item for item in dict.fromkeys(ids) if item]
    return {
        "ids": cleaned,
        "id": cleaned[0],
        "label": label,
        "match": match,
        "slug": slug,
        "effort_kind": effort_kind,
        "effort_id": effort_id,
        "position": position,
        "credits": credits,
    }


def catalog_choices(provider: str, base_id: str) -> list[dict[str, Any]]:
    """Long bridge ids plus short consumer aliases, including effort stops."""
    choices: list[dict[str, Any]] = []
    for row in load_catalog().get(provider) or []:
        slug = str(row.get("slug") or "").strip()
        if not slug:
            continue
        label = str(row.get("label") or slug)
        match = [str(item) for item in (row.get("match") or []) if str(item).strip()]
        long_id = variant_model_id(base_id, slug)
        alias = str(row.get("alias") or "").strip()
        efforts: list[tuple[str, dict[str, Any]]] = []
        for kind in ("thinking_efforts", "time_efforts"):
            for effort in row.get(kind) or []:
                if isinstance(effort, dict) and str(effort.get("id") or "").strip():
                    efforts.append((kind, effort))
        if not efforts:
            choices.append(
                _choice(
                    ids=[alias, long_id],
                    label=label,
                    match=match,
                    slug=slug,
                    effort_kind=str(row.get("effort_kind") or "").strip() or None,
                    credits=_credits(row.get("credits_per_1000000_tokens")),
                )
            )
            continue
        prefix = alias or long_id
        for kind, effort in efforts:
            effort_id = str(effort["id"]).strip()
            effort_label = str(effort.get("label") or effort_id)
            effort_match = [str(item) for item in (effort.get("match") or []) if str(item).strip()]
            short_id = f"{prefix}-{effort_id}"
            legacy_id = f"{long_id}-{effort_id}"
            position = effort.get("position")
            choices.append(
                _choice(
                    ids=[short_id, legacy_id],
                    label=effort_label,
                    match=effort_match or [effort_label, label],
                    slug=slug,
                    effort_kind=kind.removesuffix("_efforts"),
                    effort_id=effort_id,
                    position=float(position) if position is not None else None,
                    credits=_credits(effort.get("credits_per_1000000_tokens")),
                )
            )
    return choices


def resolve_requested_model(provider: str, base_id: str, requested: str | None) -> dict[str, Any] | None:
    """Map a consumer id onto a picker choice. None keeps the signed-in session default."""
    mid = (requested or base_id).strip() or base_id
    if mid == base_id:
        return None
    for choice in catalog_choices(provider, base_id):
        if mid in choice["ids"]:
            return choice
    prefix = f"{base_id}."
    if mid.startswith(prefix):
        slug = mid[len(prefix) :].strip()
        row = catalog_row_for_slug(provider, slug)
        if row:
            return _choice(
                ids=[mid],
                label=str(row.get("label") or slug),
                match=[str(item) for item in (row.get("match") or [])],
                slug=slug,
            )
        return _choice(ids=[mid], label=slug.replace("-", " "), match=[slug], slug=slug)
    return _choice(ids=[mid], label=mid.replace("-", " "), match=[mid], slug=mid)


def _public_rows(provider: str, base_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for choice in catalog_choices(provider, base_id):
        model_id = str(choice.get("id") or "")
        if not model_id or model_id in seen or model_id == base_id or model_id.startswith(f"{base_id}."):
            continue
        seen.add(model_id)
        row: dict[str, Any] = {
            "id": model_id,
            "object": "model",
            "owned_by": "forge-web-bridge",
            "name": model_id,
        }
        if choice.get("credits"):
            row["credits_per_1000000_tokens"] = dict(choice["credits"])
        rows.append(row)
    return rows


def openai_models_payload(
    provider: str,
    base_id: str,
    live_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Build GET /v1/models body from the saved consumer catalog.

    Live menu labels are ignored. The announcement is the saved alias list and its burn credits.
    """
    del live_labels
    if not expose_catalog():
        return {
            "object": "list",
            "data": [{"id": base_id, "object": "model", "owned_by": "forge-web-bridge"}],
        }

    rows = _public_rows(provider, base_id)
    everyone: list[dict[str, Any]] = list(rows)
    if provider != "gemini":
        everyone.extend(_public_rows("gemini", "granite-gemini-primary"))
    if provider != "chatgpt":
        everyone.extend(_public_rows("chatgpt", "granite-chatgpt-primary"))
    ordered = sorted(
        everyone,
        key=lambda row: float((row.get("credits_per_1000000_tokens") or {}).get("output") or 0),
        reverse=True,
    )
    rank_of = {str(row["id"]): rank for rank, row in enumerate(ordered, start=1)}
    for row in rows:
        credits = row.get("credits_per_1000000_tokens")
        if isinstance(credits, dict):
            credits["burn_rank"] = rank_of[str(row["id"])]
    rows.sort(key=lambda row: int((row.get("credits_per_1000000_tokens") or {}).get("burn_rank") or 999))
    return {"object": "list", "data": rows}
