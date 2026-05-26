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

from fleet_server.container_templates.catalog import (
    _safe_ref_path,
    _write_json_atomic,
    build_cache_file,
    bundle_fingerprint,
    load_build_cache,
    load_requirement_templates,
    save_requirement_templates,
    template_by_id,
    validate_requirement_id,
)

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


def _docker_bin() -> str:
    """Same resolution as ``docker_argv`` jobs (``fleet_server.runner``)."""
    from fleet_server import runner as fleet_runner

    return fleet_runner._docker_executable()


def _env_opted_out(name: str) -> bool:
    """True when ``name`` is set to an explicit opt-out value (restricted / disabled)."""
    v = str(os.environ.get(name) or "").strip().lower()
    return v in ("0", "false", "no")


def _template_build_network_allowed() -> bool:
    """
    Registry / default Docker network for builds and pulls.

    Opt-out model: pulls and Dockerfile builds may use the network by default.
    Set ``FLEET_TEMPLATE_BUILD_NETWORK`` to ``0``, ``false``, or ``no`` to use
    ``docker build --network none`` and to refuse ``docker pull``.
    """
    return not _env_opted_out("FLEET_TEMPLATE_BUILD_NETWORK")


def prefetch_template_images_enabled() -> bool:
    """
    Background prefetch of template images at server start.

    Default **on** (prefetch each template). Set ``FLEET_PREFETCH_TEMPLATE_IMAGES``
    to ``0``, ``false``, or ``no`` to disable (avoids slow startup on large catalogs).
    """
    return not _env_opted_out("FLEET_PREFETCH_TEMPLATE_IMAGES")


def parse_build_if_missing_query(q: dict[str, list[str]]) -> bool:
    """
    Resolve endpoint: build when cache miss unless the client explicitly passes
    ``build_if_missing=0`` / ``false`` / ``no``. Omitted parameter → build.
    """
    vals = q.get("build_if_missing")
    if vals is None:
        return True
    raw = str(vals[0] if vals else "").strip().lower()
    if raw == "":
        return True
    return raw not in ("0", "false", "no")


def meta_build_template_if_missing(meta: dict[str, Any]) -> bool:
    """
    Jobs with ``meta.use_fleet_template_image``: build/pull when missing unless
    ``meta.build_template_if_missing`` is explicitly false-ish.
    """
    if "build_template_if_missing" not in meta:
        return True
    v = meta["build_template_if_missing"]
    if v is False or v == 0:
        return False
    if isinstance(v, str) and v.strip().lower() in ("0", "false", "no"):
        return False
    return True


def prefetch_requirement_template_images(data_dir: Path) -> None:
    """Prefetch each declared template image (single-id bundles); errors are logged only."""
    try:
        doc = load_requirement_templates(data_dir)
    except (OSError, ValueError, TypeError) as ex:
        print(f"[fleet] template prefetch: load templates failed: {ex}")
        return
    templates = doc.get("templates")
    if not isinstance(templates, list):
        templates = []
    ids: list[str] = []
    for row in templates:
        if isinstance(row, dict):
            rid = str(row.get("id") or "").strip()
            if rid:
                ids.append(rid)
    print(f"[fleet] template prefetch: starting ({len(ids)} template(s))")
    for rid in ids:
        try:
            from fleet_server import container_templates as _ct

            built = _ct.run_template_build(data_dir, [rid])
            if not built.get("ok"):
                err = built.get("error", built)
                print(f"[fleet] template prefetch id={rid!r}: {err}")
        except (OSError, ValueError, TypeError, RuntimeError) as ex:
            print(f"[fleet] template prefetch id={rid!r}: {ex}")
    print("[fleet] template prefetch: finished")


def resolve_cached_image(data_dir: Path, requirement_ids: list[str]) -> dict[str, Any]:
    """Return cache record if present (does not verify docker image exists)."""
    key, fp = bundle_fingerprint(data_dir, requirement_ids)
    doc = load_build_cache(data_dir)
    entries = doc.get("entries") if isinstance(doc.get("entries"), dict) else {}
    ent = entries.get(key)
    if not isinstance(ent, dict):
        return {"ok": False, "cache_key": key, "fingerprint": fp, "image": None, "entry": None}
    img = str(ent.get("image") or "").strip()
    return {
        "ok": bool(img),
        "cache_key": key,
        "fingerprint": fp,
        "image": img or None,
        "entry": ent,
    }


def _stderr_suggests_missing_buildx(stderr: str, stdout: str) -> bool:
    """True when ``docker build`` failed because BuildKit wants ``docker buildx`` but it is absent."""
    blob = (stderr or "") + "\n" + (stdout or "")
    low = blob.lower()
    if "buildx" not in low:
        return False
    return "missing" in low or "broken" in low or "buildkit" in low


def run_template_build(data_dir: Path, requirement_ids: list[str]) -> dict[str, Any]:
    """
    Build or pull template image; update build cache.
    For ``kind: image``, runs ``docker pull``; for ``dockerfile``, ``docker build``.
    """
    key, fp = bundle_fingerprint(data_dir, requirement_ids)
    ids = sorted({validate_requirement_id(x) for x in requirement_ids})
    doc = load_requirement_templates(data_dir)

    # Single requirement templates only for docker build path; multi = combine how?
    # Plan: union of ids -> one image: build from first dockerfile that lists FROM and merge?
    # MVP: **only support single requirement id** OR multiple where all but one are image pins — simplest:
    # **Multiple requirements**: concatenate dockerfiles is hard. Support **single id** for build;
    # for multiple ids, require all `kind: image` same base — error unless len(ids)==1 for dockerfile.

    if len(ids) > 1:
        # Composite: only allow all `image` kind same ref, or fail
        refs: set[str] = set()
        kinds: list[str] = []
        for rid in ids:
            t = template_by_id(data_dir, rid)
            if not t:
                return {"ok": False, "error": f"unknown_requirement:{rid}", "cache_key": key}
            kinds.append(str(t.get("kind")))
            if str(t.get("kind")) == "image":
                refs.add(str(t.get("ref")))
        if len(refs) == 1 and all(k == "image" for k in kinds):
            image_ref = list(refs)[0]
            return _docker_pull_and_cache(data_dir, key, fp, image_ref)
        return {
            "ok": False,
            "error": "multi_requirement_build_supported_only_for_single_dockerfile_or_all_same_image",
            "cache_key": key,
        }

    rid = ids[0]
    t = template_by_id(data_dir, rid)
    if not t:
        return {"ok": False, "error": "unknown_requirement", "cache_key": key}

    if str(t.get("kind")) == "image":
        return _docker_pull_and_cache(data_dir, key, fp, str(t.get("ref")))

    dockerfile_path = _safe_ref_path(data_dir, str(t.get("ref")))
    tag = f"fleetreq/{rid}:{fp[:16]}"
    ctx = dockerfile_path.parent
    allow_net = _template_build_network_allowed()
    cmd = [
        _docker_bin(),
        "build",
        "-t",
        tag,
        "-f",
        str(dockerfile_path),
    ]
    if not allow_net:
        cmd.extend(["--network", "none"])
    cmd.append(str(ctx))

    def _run_build_once(*, buildkit: bool) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "DOCKER_BUILDKIT": "1" if buildkit else "0"}
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600,
            env=env,
        )

    bk_pref = os.environ.get("FLEET_DOCKER_BUILDKIT", "").strip().lower()
    try:
        if bk_pref in ("0", "false", "no", "off"):
            r = _run_build_once(buildkit=False)
        elif bk_pref in ("1", "true", "yes", "on"):
            r = _run_build_once(buildkit=True)
        else:
            r = _run_build_once(buildkit=True)
            if r.returncode != 0 and _stderr_suggests_missing_buildx(r.stderr or "", r.stdout or ""):
                r = _run_build_once(buildkit=False)
    except (OSError, subprocess.TimeoutExpired) as ex:
        _record_build_error(data_dir, key, fp, str(ex)[:2000])
        return {"ok": False, "error": str(ex)[:2000], "cache_key": key}

    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[:8000]
        _record_build_error(data_dir, key, fp, err)
        return {"ok": False, "error": err, "cache_key": key, "returncode": r.returncode}

    _record_build_success(data_dir, key, fp, tag, dockerfile_path)
    return {"ok": True, "image": tag, "cache_key": key, "fingerprint": fp}


def _docker_pull_and_cache(data_dir: Path, key: str, fp: str, image_ref: str) -> dict[str, Any]:
    if not _template_build_network_allowed():
        return {
            "ok": False,
            "error": "docker_pull_blocked_FLEET_TEMPLATE_BUILD_NETWORK_opt_out",
            "cache_key": key,
        }
    try:
        r = subprocess.run(
            [_docker_bin(), "pull", image_ref],
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        _record_build_error(data_dir, key, fp, str(ex)[:2000])
        return {"ok": False, "error": str(ex)[:2000], "cache_key": key}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "")[:8000]
        _record_build_error(data_dir, key, fp, err)
        return {"ok": False, "error": err, "cache_key": key}
    _record_build_success(data_dir, key, fp, image_ref, None)
    return {"ok": True, "image": image_ref, "cache_key": key, "fingerprint": fp}


def _record_build_success(
    data_dir: Path, key: str, fp: str, image: str, dockerfile_path: Path | None
) -> None:
    doc = load_build_cache(data_dir)
    entries = doc.get("entries") if isinstance(doc.get("entries"), dict) else {}
    sha = ""
    if dockerfile_path is not None and dockerfile_path.is_file():
        try:
            sha = hashlib.sha256(dockerfile_path.read_bytes()).hexdigest()
        except OSError:
            sha = ""
    entries[key] = {
        "image": image,
        "fingerprint": fp,
        "built_at": time.time(),
        "dockerfile_sha256": sha,
        "last_error": None,
    }
    doc["entries"] = entries
    _write_json_atomic(build_cache_file(data_dir), doc)


def _record_build_error(data_dir: Path, key: str, fp: str, err: str) -> None:
    doc = load_build_cache(data_dir)
    entries = doc.get("entries") if isinstance(doc.get("entries"), dict) else {}
    prev = entries.get(key) if isinstance(entries.get(key), dict) else {}
    entries[key] = {
        **prev,
        "fingerprint": fp,
        "last_error": err[:8000],
        "failed_at": time.time(),
    }
    doc["entries"] = entries
    _write_json_atomic(build_cache_file(data_dir), doc)


