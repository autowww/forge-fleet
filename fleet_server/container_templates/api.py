"""Requirement templates, build cache, and Docker image resolution for Fleet-managed job images."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fleet_server import workspace_bundle

from fleet_server.container_templates.build import resolve_cached_image, run_template_build
from fleet_server.container_templates.catalog import (
    build_cache_file,
    dockerfiles_allow_root,
    load_build_cache,
    load_requirement_templates,
    requirement_templates_file,
)
from fleet_server.container_templates.build import _BUILD_LOCK, _BUILD_STATE

_REQ_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

_BUILD_LOCK = threading.Lock()
_BUILD_STATE: dict[str, Any] = {"last_build": None, "in_progress": False}

DEFAULT_REQUIREMENT_TEMPLATES: dict[str, Any] = {
    "version": 1,
    "templates": [],
}

# Conventional requirement id for certificator source-ingest workers (not auto-seeded; install via
# ``PUT /v1/container-templates/{id}/package`` with a tar.gz from forge-certificators).
BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID = "certificator_source_ingest_worker"

DEFAULT_BUILD_CACHE: dict[str, Any] = {"version": 1, "entries": {}}


def templates_api_payload(data_dir: Path) -> dict[str, Any]:
    doc = load_requirement_templates(data_dir)
    return {
        "ok": True,
        "version": doc.get("version"),
        "templates": doc.get("templates"),
        "paths": {
            "requirement_templates_file": str(requirement_templates_file(data_dir)),
            "build_cache_file": str(build_cache_file(data_dir)),
            "dockerfiles_root": str(dockerfiles_allow_root(data_dir)),
        },
    }


def status_api_payload(data_dir: Path) -> dict[str, Any]:
    doc = load_build_cache(data_dir)
    return {"ok": True, "build_cache": doc, "build_state": dict(_BUILD_STATE)}


def resolve_api_payload(data_dir: Path, requirement_ids: list[str], *, build_if_missing: bool) -> dict[str, Any]:
    try:
        cached = resolve_cached_image(data_dir, requirement_ids)
    except ValueError as ex:
        return {"ok": False, "error": str(ex)}
    if cached.get("ok") and cached.get("image"):
        return {**cached, "ok": True, "built": False}
    if not build_if_missing:
        return {**cached, "built": False, "detail": "not_in_cache", "ok": True}
    built: dict[str, Any] = {}
    with _BUILD_LOCK:
        _BUILD_STATE["in_progress"] = True
        try:
            built = run_template_build(data_dir, requirement_ids)
        finally:
            _BUILD_STATE["in_progress"] = False
            _BUILD_STATE["last_build"] = built
    if built.get("ok"):
        return {
            "ok": True,
            "image": built.get("image"),
            "cache_key": built.get("cache_key"),
            "fingerprint": built.get("fingerprint"),
            "built": True,
        }
    return {"ok": False, **built}


def _docker_run_word_index(argv: list[str]) -> int | None:
    """Return index of the ``run`` subcommand token, or None."""
    if not argv:
        return None
    base = Path(str(argv[0])).name.lower()
    if base != "docker":
        return None
    if len(argv) >= 2 and argv[1] == "run":
        return 1
    if (
        len(argv) >= 3
        and str(argv[1]).lower() == "container"
        and argv[2] == "run"
    ):
        return 2
    return None


def inject_template_image_into_docker_argv(argv: list[str], image_replacement: str) -> list[str]:
    """
    Replace the image token in Docker argv after ``docker … run …`` / ``docker container run``.

    Conservative parser: after ``run``, skip ``-opt`` / ``--opt [val]`` tokens, then replace next non-option.
    Accepts a path to the docker binary (basename ``docker``).
    """
    ri = _docker_run_word_index(argv)
    if ri is None:
        return argv
    i = ri + 1
    n = len(argv)
    while i < n:
        a = argv[i]
        if a == "--":
            i += 1
            break
        if a.startswith("--"):
            eq = a.find("=")
            if eq != -1:
                i += 1
                continue
            if i + 1 < n and not str(argv[i + 1]).startswith("-"):
                i += 2
                continue
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            if i + 1 < n and not str(argv[i + 1]).startswith("-"):
                i += 2
            else:
                i += 1
            continue
        argv[i] = image_replacement
        return argv
    return argv
