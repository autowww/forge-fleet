"""Mirror Open WebUI models as forge-squid-<slug> and resolve back to upstream ids."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import branding

SQUID_PREFIX = "forge-squid-"
DEFAULT_UPSTREAM_MODEL = "qwen3.5:2b-q4_K_M"
DEFAULT_SQUID_ID = f"{SQUID_PREFIX}qwen352bq4km"
_SLUG_STRIP = str.maketrans("", "", ".:_-/")


@dataclass(frozen=True)
class SquidEntry:
    squid_id: str
    upstream_id: str
    slug: str


@dataclass
class SquidCatalog:
    entries: list[SquidEntry] = field(default_factory=list)
    collisions: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def empty(cls, *, error: str | None = None) -> "SquidCatalog":
        return cls(error=error)

    def squid_ids(self) -> list[str]:
        return [e.squid_id for e in self.entries]

    def resolve_client_model(self, model: str) -> tuple[str, str]:
        """Return ``(client_squid_id, upstream_openwebui_id)``."""
        if not model.startswith(SQUID_PREFIX):
            raise ValueError("not_a_squid_model")
        slug = model[len(SQUID_PREFIX) :].lower()
        for entry in self.entries:
            if entry.slug == slug or entry.squid_id == model:
                return entry.squid_id, entry.upstream_id
        raise KeyError(model)

    def trace(self) -> dict[str, Any]:
        return {
            "squid_count": len(self.entries),
            "collisions": self.collisions,
            "dropped_count": len(self.dropped),
            "error": self.error,
            "map": {e.squid_id: e.upstream_id for e in self.entries},
        }


def openwebui_base_url() -> str:
    return (
        os.environ.get("FORGE_SQUID_OPENWEBUI_BASE_URL", "").strip()
        or os.environ.get("FORGE_LLM_OPENWEBUI_BASE_URL", "").strip()
    ).rstrip("/")


def openwebui_api_key() -> str:
    return (
        os.environ.get("FORGE_SQUID_OPENWEBUI_API_KEY", "").strip()
        or os.environ.get("FORGE_LLM_OPENWEBUI_API_KEY", "").strip()
        or os.environ.get("OPEN_WEBUI_API_KEY", "").strip()
    )


def upstream_tail(model_id: str) -> str:
    if "." not in model_id:
        return model_id
    left, right = model_id.split(".", 1)
    # Connection ids use hyphens (granite-llm) or a short alpha tag (xai). Model ids may contain dots (qwen3.5, composer-2.5).
    if left.isalpha() and left.islower():
        return right
    if "-" in left and (":" in right or len(right) > 4):
        return right
    return model_id


def slugify(model_id: str) -> str:
    return upstream_tail(model_id).translate(_SLUG_STRIP).lower()


def is_shim_upstream_id(model_id: str) -> bool:
    low = model_id.lower()
    if low.startswith(SQUID_PREFIX):
        return True
    if low == "forge-2b" or low.endswith(".forge-2b"):
        return True
    if branding.is_owui_shim_connection_id(model_id):
        return True
    return False


def build_catalog(rows: list[dict[str, Any]]) -> SquidCatalog:
    dropped: list[str] = []
    by_slug: dict[str, list[str]] = {}
    candidates: list[tuple[str, str]] = []
    for row in rows:
        mid = str(row.get("id") or "").strip()
        if not mid:
            continue
        if is_shim_upstream_id(mid):
            dropped.append(mid)
            continue
        slug = slugify(mid)
        if not slug:
            dropped.append(mid)
            continue
        candidates.append((mid, slug))
        by_slug.setdefault(slug, []).append(mid)
    collisions = [{"slug": slug, "upstream_ids": ids} for slug, ids in by_slug.items() if len(ids) > 1]
    blocked = {slug for slug, ids in by_slug.items() if len(ids) > 1}
    entries = [
        SquidEntry(squid_id=f"{SQUID_PREFIX}{slug}", upstream_id=mid, slug=slug)
        for mid, slug in candidates
        if slug not in blocked
    ]
    entries.sort(key=lambda e: e.squid_id)
    return SquidCatalog(entries=entries, collisions=collisions, dropped=dropped)


def parse_owui_models_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        raw = data.get("data")
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


async def fetch_catalog(client: httpx.AsyncClient, base_url: str, api_key: str) -> SquidCatalog:
    if not base_url:
        return SquidCatalog.empty(error="openwebui_base_url_not_configured")
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = await client.get(f"{base_url.rstrip('/')}/api/models", headers=headers)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as ex:
        return SquidCatalog.empty(error=f"{type(ex).__name__}")
    return build_catalog(parse_owui_models_payload(payload))


def completion_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/chat/completions"


def default_squid_id() -> str:
    return (os.environ.get("FORGE_SQUID_DEFAULT_MODEL") or DEFAULT_SQUID_ID).strip() or DEFAULT_SQUID_ID


def outbound_chat_model(body: dict[str, Any], upstream_id: str, fallback: str = DEFAULT_UPSTREAM_MODEL) -> str:
    return upstream_id or fallback
