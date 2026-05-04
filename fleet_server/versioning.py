"""Forge Fleet release identity — aligned with Studio-style semver (``pyproject.toml`` is source of truth)."""

from __future__ import annotations

import importlib.metadata
import os
import re
import subprocess
import threading
from pathlib import Path

# Bump when ``fleet_server/store.py`` ships a new SQLite migration for ``fleet_schema`` / jobs.
FLEET_DB_SCHEMA_VERSION = 6

# Bump when ``templates_catalog.TEMPLATE_LIB`` gains a breaking contract change.
FLEET_TEMPLATE_LIB_VERSION = 4


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


_UNSET = object()
_git_sha_lock = threading.Lock()
_git_sha_cached: str | object = _UNSET


def reset_git_sha_cache() -> None:
    """Clear memoized git SHA (tests only, or after changing ``FLEET_GIT_*`` env in-process)."""
    global _git_sha_cached
    with _git_sha_lock:
        _git_sha_cached = _UNSET


def _git_rev_short_head(repo: Path) -> str | None:
    """Return short SHA from ``git rev-parse`` when ``repo`` is a git checkout."""
    git_dir = repo / ".git"
    if not git_dir.exists():
        return None
    try:
        r = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=4,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    sha = (r.stdout or "").strip()
    return sha[:40] if sha else None


def _probe_git_sha_from_disk() -> str | None:
    """
    When ``FLEET_GIT_SHA`` is unset, resolve from ``FLEET_GIT_ROOT`` (user/system rsync installs
    ship no ``.git`` under the running tree) or from the package parent directory when it is a clone.

    If ``FLEET_GIT_ROOT`` is set but is not a git checkout, return ``None`` (do not fall back to
    the package tree — that would mis-report the identity of an rsynced runtime).
    """
    gr = str(os.environ.get("FLEET_GIT_ROOT") or "").strip()
    if gr:
        return _git_rev_short_head(Path(gr).expanduser().resolve())
    pkg_root = Path(__file__).resolve().parent.parent
    return _git_rev_short_head(pkg_root)


def git_sha_short() -> str:
    env = str(os.environ.get("FLEET_GIT_SHA") or os.environ.get("SOURCE_GIT_COMMIT") or "").strip()[:40]
    if env:
        return env
    global _git_sha_cached
    with _git_sha_lock:
        if _git_sha_cached is not _UNSET:
            return str(_git_sha_cached)
        probed = _probe_git_sha_from_disk()
        _git_sha_cached = probed if probed else ""
        return str(_git_sha_cached)


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
