"""Forge Squid environment variables (FORGE_SQUID_* only)."""

from __future__ import annotations

import os
from pathlib import Path

from . import branding


def first_env(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return default


def config_dir() -> Path:
    override = first_env("FORGE_SQUID_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / branding.CONFIG_DIR_NAME


def lab_env_file() -> Path:
    return config_dir() / "lab.env"


def default_cache_dir() -> Path:
    explicit = first_env("FORGE_SQUID_CACHE_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return config_dir() / "cache"
