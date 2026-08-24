"""Per-app migration bundle total-size limits (HTTP chunk size is separate — 64 MiB default)."""

from __future__ import annotations

import json
import os
from typing import Any

# Global default for apps without a specific cap.
_DEFAULT_GLOBAL_MAX_BYTES = 500 * 1024 * 1024  # 500 MiB

# Built-in per-app totals (override via env — see max_bundle_upload_bytes).
_BUILTIN_APP_MAX_BYTES: dict[str, int] = {
    "forge-market": 500 * 1024**3,  # 500 GiB
}


def normalize_app_slug(raw: str) -> str:
    return raw.strip().lower().replace("_", "-")


def migration_app_slug(row: dict[str, Any] | None) -> str:
    """Resolve app slug from a Fleet migration row."""
    if not row:
        return ""
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    for key in ("app_slug", "recipe_id", "recipe"):
        val = normalize_app_slug(str(meta.get(key) or ""))
        if val:
            return val
    src = normalize_app_slug(str(row.get("source_label") or ""))
    if src in ("forge-market", "market"):
        return "forge-market"
    return src


def _parse_positive_int(raw: str, default: int) -> int:
    try:
        return max(1, int(raw.strip(), 10))
    except (TypeError, ValueError, AttributeError):
        return default


def _env_app_overrides() -> dict[str, int]:
    out: dict[str, int] = {}
    raw = str(os.environ.get("FLEET_MIGRATION_BUNDLE_MAX_BYTES_BY_APP") or "").strip()
    if raw:
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict):
            for key, val in doc.items():
                slug = normalize_app_slug(str(key))
                if slug:
                    try:
                        out[slug] = max(1, int(val))
                    except (TypeError, ValueError):
                        continue
    prefix = "FLEET_MIGRATION_BUNDLE_MAX_BYTES_"
    for key, val in os.environ.items():
        if not key.startswith(prefix) or key == f"{prefix}BY_APP":
            continue
        slug = normalize_app_slug(key[len(prefix) :])
        if slug:
            out[slug] = _parse_positive_int(str(val), out.get(slug, 0) or 1)
    return out


def max_bundle_upload_bytes(migration_row: dict[str, Any] | None = None) -> int:
    """Max assembled migration bundle size for this migration's app."""
    app = migration_app_slug(migration_row)
    overrides = _env_app_overrides()
    if app and app in overrides:
        return overrides[app]
    if app and app in _BUILTIN_APP_MAX_BYTES:
        return _BUILTIN_APP_MAX_BYTES[app]
    return _parse_positive_int(
        str(os.environ.get("FLEET_MIGRATION_BUNDLE_UPLOAD_MAX_BYTES") or ""),
        _DEFAULT_GLOBAL_MAX_BYTES,
    )


# Extract cap is independent of compressed upload size (gzip can be much smaller
# than the tree). Default stays 2 GiB for unknown apps; forge-market matches the
# 500 GiB upload builtin so a full local Market corpus can extract on Granite.
_DEFAULT_GLOBAL_MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
_BUILTIN_APP_MAX_UNCOMPRESSED_BYTES: dict[str, int] = {
    "forge-market": 500 * 1024**3,
}


def _env_uncompressed_overrides() -> dict[str, int]:
    out: dict[str, int] = {}
    raw = str(os.environ.get("FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES_BY_APP") or "").strip()
    if raw:
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict):
            for key, val in doc.items():
                slug = normalize_app_slug(str(key))
                if slug:
                    try:
                        out[slug] = max(1, int(val))
                    except (TypeError, ValueError):
                        continue
    prefix = "FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES_"
    for key, val in os.environ.items():
        if not key.startswith(prefix) or key.endswith("_BY_APP"):
            continue
        if key == "FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES":
            continue
        slug = normalize_app_slug(key[len(prefix) :])
        if slug:
            out[slug] = _parse_positive_int(str(val), out.get(slug, 0) or 1)
    return out


def max_bundle_uncompressed_bytes(migration_row: dict[str, Any] | None = None) -> int:
    """Max uncompressed extract size for this migration's app."""
    app = migration_app_slug(migration_row)
    overrides = _env_uncompressed_overrides()
    if app and app in overrides:
        return overrides[app]
    if app and app in _BUILTIN_APP_MAX_UNCOMPRESSED_BYTES:
        return _BUILTIN_APP_MAX_UNCOMPRESSED_BYTES[app]
    return _parse_positive_int(
        str(os.environ.get("FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES") or ""),
        _DEFAULT_GLOBAL_MAX_UNCOMPRESSED_BYTES,
    )


_DEFAULT_GLOBAL_MAX_FILES = 200_000
_BUILTIN_APP_MAX_FILES: dict[str, int] = {
    "forge-market": 5_000_000,
}


def max_bundle_files(migration_row: dict[str, Any] | None = None) -> int:
    """Max regular files allowed in a migration bundle extract."""
    app = migration_app_slug(migration_row)
    raw_map = str(os.environ.get("FLEET_MIGRATION_BUNDLE_MAX_FILES_BY_APP") or "").strip()
    if raw_map:
        try:
            doc = json.loads(raw_map)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict) and app:
            try:
                return max(1, int(doc.get(app)))
            except (TypeError, ValueError):
                pass
    if app:
        env_key = "FLEET_MIGRATION_BUNDLE_MAX_FILES_" + app.upper().replace("-", "_")
        env_val = str(os.environ.get(env_key) or "").strip()
        if env_val:
            return _parse_positive_int(env_val, _DEFAULT_GLOBAL_MAX_FILES)
        if app in _BUILTIN_APP_MAX_FILES:
            return _BUILTIN_APP_MAX_FILES[app]
    return _parse_positive_int(
        str(os.environ.get("FLEET_MIGRATION_BUNDLE_MAX_FILES") or ""),
        _DEFAULT_GLOBAL_MAX_FILES,
    )
