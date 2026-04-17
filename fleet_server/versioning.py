"""Forge Fleet release identity — aligned with Studio-style semver (``pyproject.toml`` is source of truth)."""

from __future__ import annotations

import importlib.metadata
import os
import re
from pathlib import Path

# Bump when ``fleet_server/store.py`` ships a new SQLite migration for ``fleet_schema`` / jobs.
FLEET_DB_SCHEMA_VERSION = 4

# Bump when ``templates_catalog.TEMPLATE_LIB`` gains a breaking contract change.
FLEET_TEMPLATE_LIB_VERSION = 3


def _read_pyproject_semver() -> str:
    root = Path(__file__).resolve().parent.parent
    py = root / "pyproject.toml"
    if not py.is_file():
        return "0.0.0"
    try:
        raw = py.read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    m = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', raw)
    return m.group(1).strip() if m else "0.0.0"


def package_semver() -> str:
    """Installed distribution version, or ``pyproject.toml`` when running from a source checkout."""
    try:
        return importlib.metadata.version("forge-fleet").strip()
    except importlib.metadata.PackageNotFoundError:
        return _read_pyproject_semver()


def git_sha_short() -> str:
    return str(os.environ.get("FLEET_GIT_SHA") or os.environ.get("SOURCE_GIT_COMMIT") or "").strip()[:40]


def fleet_server_version_string() -> str:
    return f"forge-fleet/{package_semver()}"


def version_api_payload(*, db_schema_version: int, db_package_semver: str | None) -> dict[str, object]:
    sem = package_semver()
    return {
        "ok": True,
        "service": "forge-fleet",
        "package_semver": sem,
        "db_schema_version": int(db_schema_version),
        "db_recorded_package_semver": db_package_semver,
        "template_lib_version": FLEET_TEMPLATE_LIB_VERSION,
        "server_version": fleet_server_version_string(),
        "git_sha": git_sha_short() or None,
        "release_note": "Bump ``pyproject.toml`` / ``[project].version`` for each release; bump FLEET_DB_SCHEMA_VERSION when SQLite migrations ship.",
    }
