"""Mirror Open WebUI models as forge-squid-<slug> and resolve back to upstream ids."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import branding, env_keys

SQUID_PREFIX = "forge-squid-"
OWUI_CONNECTION_PREFIX = "forge-squid"
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
        """Return ``(client_squid_id, upstream_openwebui_id)``.

        Open WebUI calls back with the id from ``GET /v1/models``, which is the
        bare slug (``composer``), not ``forge-squid.composer``.
        """
        raw = model.strip()
        try:
            canonical = normalize_squid_client_id(raw)
        except ValueError:
            canonical = ""
        slug = canonical[len(SQUID_PREFIX) :].lower() if canonical.lower().startswith(SQUID_PREFIX) else slugify(raw)
        for entry in self.entries:
            if entry.slug == slug or (canonical and entry.squid_id == canonical):
                return entry.squid_id, entry.upstream_id
        if not canonical:
            raise ValueError("not_a_squid_model")
        raise KeyError(model)

    def trace(self) -> dict[str, Any]:
        return {
            "squid_count": len(self.entries),
            "collisions": self.collisions,
            "dropped_count": len(self.dropped),
            "error": self.error,
            "map": {e.squid_id: e.upstream_id for e in self.entries},
            "owui_ids": {f"{OWUI_CONNECTION_PREFIX}.{e.slug}": e.upstream_id for e in self.entries},
        }


def slug_from_squid_id(squid_id: str) -> str:
    if squid_id.startswith(SQUID_PREFIX):
        return squid_id[len(SQUID_PREFIX) :]
    return squid_id


def owui_aggregated_id(slug: str) -> str:
    """Open WebUI id with connection prefix only once: ``forge-squid.<slug>``."""
    slug = slug_from_squid_id(slug.strip())
    return f"{OWUI_CONNECTION_PREFIX}.{slug}"


def public_model_id(entry: SquidEntry) -> str:
    """Id advertised on ``GET /v1/models`` (slug only; OWUI prepends ``forge-squid.``)."""
    return entry.slug


def normalize_squid_client_id(model: str) -> str:
    """Accept OWUI ``forge-squid.<slug>``, legacy ``forge-squid.forge-squid-*``, or ``forge-squid-*``."""
    m = model.strip()
    low = m.lower()
    prefix = f"{OWUI_CONNECTION_PREFIX}."
    if low.startswith(prefix):
        rest = m.split(".", 1)[1].strip()
        rlow = rest.lower()
        if rlow.startswith(SQUID_PREFIX):
            return rest if rest.lower().startswith(SQUID_PREFIX) else f"{SQUID_PREFIX}{rlow}"
        return f"{SQUID_PREFIX}{rlow}"
    if low.startswith(SQUID_PREFIX):
        return m
    raise ValueError("not_a_squid_model")


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


def extra_upstream_ids() -> list[str]:
    """Comma-separated Open WebUI model ids to mirror even when absent from /api/models."""
    raw = env_keys.first_env("FORGE_SQUID_EXTRA_UPSTREAM")
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def merge_extra_upstream(catalog: SquidCatalog) -> SquidCatalog:
    extra = extra_upstream_ids()
    if not extra:
        return catalog
    slugs = {e.slug for e in catalog.entries}
    squids = {e.squid_id for e in catalog.entries}
    entries = list(catalog.entries)
    for mid in extra:
        if is_shim_upstream_id(mid):
            continue
        slug = slugify(mid)
        if not slug or slug in slugs:
            continue
        sid = f"{SQUID_PREFIX}{slug}"
        if sid in squids:
            continue
        entries.append(SquidEntry(squid_id=sid, upstream_id=mid, slug=slug))
        slugs.add(slug)
        squids.add(sid)
    entries.sort(key=lambda e: e.squid_id)
    return SquidCatalog(entries=entries, collisions=catalog.collisions, dropped=list(catalog.dropped), error=catalog.error)


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
    return merge_extra_upstream(SquidCatalog(entries=entries, collisions=collisions, dropped=dropped))


def parse_owui_models_payload(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        raw = data.get("data")
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def catalog_cache_path() -> Path:
    override = env_keys.first_env("FORGE_SQUID_CATALOG_CACHE_FILE")
    if override:
        return Path(override).expanduser()
    return env_keys.config_dir() / "catalog-cache.json"


def load_disk_cache() -> SquidCatalog | None:
    path = catalog_cache_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text())
        rows = payload.get("upstream_rows")
        if not isinstance(rows, list):
            return None
        catalog = build_catalog([r for r in rows if isinstance(r, dict)])
        catalog = merge_extra_upstream(catalog)
        if catalog.error and not catalog.entries:
            return None
        return catalog
    except (OSError, ValueError, TypeError):
        return None


def save_disk_cache(rows: list[dict[str, Any]], catalog: SquidCatalog) -> None:
    from datetime import datetime, timezone

    path = catalog_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "upstream_rows": rows,
                "squid_map": catalog.trace().get("map", {}),
                "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


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
    rows = parse_owui_models_payload(payload)
    for mid in extra_upstream_ids():
        rows.append({"id": mid})
    catalog = build_catalog(rows)
    if catalog.entries:
        save_disk_cache(rows, catalog)
    return catalog


def completion_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/chat/completions"


def llm_gateway_completion_url(base_url: str) -> str:
    """OpenAI-compatible forge-llm gateway (…/v1 → …/v1/chat/completions)."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def default_squid_id() -> str:
    return (os.environ.get("FORGE_SQUID_DEFAULT_MODEL") or DEFAULT_SQUID_ID).strip() or DEFAULT_SQUID_ID


def outbound_chat_model(body: dict[str, Any], upstream_id: str, fallback: str = DEFAULT_UPSTREAM_MODEL) -> str:
    return upstream_id or fallback
