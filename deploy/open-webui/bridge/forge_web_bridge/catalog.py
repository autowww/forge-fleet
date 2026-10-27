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


def openai_models_payload(
    provider: str,
    base_id: str,
    live_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Build GET /v1/models body."""
    data: list[dict[str, str]] = [
        {
            "id": base_id,
            "object": "model",
            "owned_by": "forge-web-bridge",
        }
    ]
    if not expose_catalog():
        return {"object": "list", "data": data}

    seen_slugs: set[str] = set()
    rows = list(load_catalog().get(provider) or [])

    if live_labels:
        for label in live_labels:
            label = str(label).strip()
            if not label:
                continue
            matched = False
            for row in rows:
                matches = [str(row.get("label") or "")] + list(row.get("match") or [])
                if any(label == m or m.lower() in label.lower() for m in matches if m):
                    slug = str(row["slug"])
                    if slug not in seen_slugs:
                        seen_slugs.add(slug)
                        data.append(
                            {
                                "id": variant_model_id(base_id, slug),
                                "object": "model",
                                "owned_by": "forge-web-bridge",
                            }
                        )
                    matched = True
                    break
            if not matched:
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", label.lower()).strip("-")[:48]
                if slug and slug not in seen_slugs:
                    seen_slugs.add(slug)
                    data.append(
                        {
                            "id": variant_model_id(base_id, slug),
                            "object": "model",
                            "owned_by": "forge-web-bridge",
                        }
                    )

    for row in rows:
        slug = str(row.get("slug") or "").strip()
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        data.append(
            {
                "id": variant_model_id(base_id, slug),
                "object": "model",
                "owned_by": "forge-web-bridge",
            }
        )

    return {"object": "list", "data": data}
