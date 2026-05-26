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


def requirement_templates_file(data_dir: Path) -> Path:
    return Path(data_dir).resolve() / "etc" / "containers" / "requirement_templates.json"


def build_cache_file(data_dir: Path) -> Path:
    return Path(data_dir).resolve() / "etc" / "containers" / "build_cache.json"


def dockerfiles_allow_root(data_dir: Path) -> Path:
    """Dockerfiles must live under this directory (refs are relative to ``etc/containers/``)."""
    return Path(data_dir).resolve() / "etc" / "containers"


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def max_template_package_upload_bytes() -> int:
    """Max HTTP body size for ``PUT …/container-templates/{id}/package`` (compressed tarball)."""
    raw = str(os.environ.get("FLEET_TEMPLATE_PACKAGE_UPLOAD_MAX_BYTES") or "").strip()
    if not raw:
        return 64 * 1024 * 1024
    try:
        return max(1_048_576, int(raw, 10))
    except ValueError:
        return 64 * 1024 * 1024


def _template_package_extract_limits() -> dict[str, int]:
    raw_unc = str(os.environ.get("FLEET_TEMPLATE_PACKAGE_MAX_UNCOMPRESSED_BYTES") or "").strip()
    try:
        max_unc = max(1_048_576, int(raw_unc, 10)) if raw_unc else 120 * 1024 * 1024
    except ValueError:
        max_unc = 120 * 1024 * 1024
    raw_mf = str(os.environ.get("FLEET_TEMPLATE_PACKAGE_MAX_FILES") or "").strip()
    try:
        max_files = max(10, int(raw_mf, 10)) if raw_mf else 5000
    except ValueError:
        max_files = 5000
    raw_md = str(os.environ.get("FLEET_TEMPLATE_PACKAGE_MAX_PATH_DEPTH") or "").strip()
    try:
        max_depth = max(4, int(raw_md, 10)) if raw_md else 40
    except ValueError:
        max_depth = 40
    return {
        "max_uncompressed_bytes": max_unc,
        "max_files": max_files,
        "max_path_depth": max_depth,
    }


def resolve_dockerfile_context_dir(unpacked: Path) -> Path | None:
    """
    Return the build context directory containing ``Dockerfile``.

    Accepts a flat archive (``Dockerfile`` at root) or a single top-level folder that holds it.
    """
    if (unpacked / "Dockerfile").is_file():
        return unpacked.resolve()
    subs = sorted((p for p in unpacked.iterdir() if p.is_dir()), key=lambda p: p.name)
    if len(subs) == 1 and (subs[0] / "Dockerfile").is_file():
        return subs[0].resolve()
    return None


def apply_requirement_template_package(
    data_dir: Path,
    requirement_id: str,
    data: bytes,
    *,
    title: str = "",
    notes: str = "",
    replace: bool = True,
) -> dict[str, Any]:
    """
    Extract ``.tar.gz`` (or tar) under ``etc/containers/dockerfiles/{id}/`` and upsert the row in
    ``requirement_templates.json``. Docker build context is the directory that contains ``Dockerfile``.
    """
    data_dir = data_dir.resolve()
    try:
        rid = validate_requirement_id(requirement_id)
    except ValueError:
        return {"ok": False, "error": "invalid_requirement_id", "detail": str(requirement_id)[:200]}
    if not data:
        return {"ok": False, "error": "empty_body"}

    existing = template_by_id(data_dir, rid)
    dest_dir = dockerfiles_allow_root(data_dir) / "dockerfiles" / rid
    if not replace and existing is not None and (dest_dir / "Dockerfile").is_file():
        return {"ok": False, "error": "template_exists", "detail": "pass replace=1 to overwrite"}

    ensure_template_layout(data_dir)
    root_df = dockerfiles_allow_root(data_dir)
    staging = root_df / "dockerfiles" / f".upload-{rid}-{uuid.uuid4().hex}"
    lim = _template_package_extract_limits()
    try:
        err = workspace_bundle.extract_tarball_bytes_to_directory(
            data,
            staging,
            max_uncompressed_bytes=int(lim["max_uncompressed_bytes"]),
            max_files=int(lim["max_files"]),
            max_path_depth=int(lim["max_path_depth"]),
        )
        if err:
            return {"ok": False, "error": "extract_failed", "detail": err}
        ctx = resolve_dockerfile_context_dir(staging)
        if ctx is None:
            return {
                "ok": False,
                "error": "dockerfile_missing",
                "detail": "archive must contain Dockerfile at root or under a single top-level directory",
            }
        if dest_dir.is_dir():
            shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.copytree(ctx, dest_dir, dirs_exist_ok=False)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    ref = f"dockerfiles/{rid}/Dockerfile"
    try:
        row = validate_template_row(
            data_dir,
            {
                "id": rid,
                "title": (title.strip() or f"Dockerfile template {rid}")[:200],
                "kind": "dockerfile",
                "ref": ref,
                "notes": (
                    notes.strip()
                    or (
                        "Installed via PUT /v1/container-templates/{requirement_id}/package (tar.gz). "
                        "Edit via PUT /v1/container-templates or re-upload."
                    )
                )[:4000],
            },
        )
    except ValueError as ex:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return {"ok": False, "error": "validation_failed", "detail": str(ex)[:800]}

    doc = load_requirement_templates(data_dir)
    templates = [t for t in (doc.get("templates") or []) if isinstance(t, dict) and str(t.get("id")) != rid]
    templates.append(row)
    out_doc = {"version": int(doc.get("version") or 1), "templates": templates}
    save_requirement_templates(data_dir, out_doc)
    upload_sha = hashlib.sha256(data).hexdigest()
    return {
        "ok": True,
        "id": rid,
        "ref": ref,
        "sha256": upload_sha,
        "upload_bytes": len(data),
    }


def ensure_template_layout(data_dir: Path) -> None:
    data_dir = data_dir.resolve()
    rt = requirement_templates_file(data_dir)
    if not rt.is_file():
        _write_json_atomic(rt, DEFAULT_REQUIREMENT_TEMPLATES)
    bc = build_cache_file(data_dir)
    if not bc.is_file():
        _write_json_atomic(bc, DEFAULT_BUILD_CACHE)
    (dockerfiles_allow_root(data_dir) / "dockerfiles").mkdir(parents=True, exist_ok=True)


def load_requirement_templates(data_dir: Path) -> dict[str, Any]:
    ensure_template_layout(data_dir)
    p = requirement_templates_file(data_dir)
    try:
        o = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy_default_templates()
    return o if isinstance(o, dict) else copy_default_templates()


def copy_default_templates() -> dict[str, Any]:
    return copy.deepcopy(DEFAULT_REQUIREMENT_TEMPLATES)


def load_build_cache(data_dir: Path) -> dict[str, Any]:
    ensure_template_layout(data_dir)
    p = build_cache_file(data_dir)
    try:
        o = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_BUILD_CACHE)
    return o if isinstance(o, dict) else {"version": 1, "entries": {}}


def validate_requirement_id(rid: str) -> str:
    s = str(rid or "").strip().lower()
    if not _REQ_ID_RE.match(s):
        raise ValueError("invalid_requirement_id")
    return s


def _safe_ref_path(data_dir: Path, ref: str) -> Path:
    """Resolve ``ref`` relative to ``etc/containers``; must stay under that tree."""
    root = dockerfiles_allow_root(data_dir).resolve()
    raw = str(ref or "").strip().replace("\\", "/").lstrip("/")
    if not raw or ".." in raw.split("/"):
        raise ValueError("invalid_template_ref")
    p = (root / raw).resolve()
    try:
        p.relative_to(root)
    except ValueError as e:
        raise ValueError("template_ref_escape") from e
    return p


def validate_template_row(data_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    rid = validate_requirement_id(str(row.get("id") or ""))
    title = str(row.get("title") or rid).strip()[:200]
    kind = str(row.get("kind") or "").strip().lower()
    if kind not in ("dockerfile", "image"):
        raise ValueError("template_kind_invalid")
    ref = str(row.get("ref") or "").strip()
    if not ref:
        raise ValueError("template_ref_required")
    if kind == "dockerfile":
        p = _safe_ref_path(data_dir, ref)
        if not p.is_file():
            raise ValueError("dockerfile_missing")
    elif kind == "image":
        # Hyphen must not sit between ``/`` and ``:`` (that would be an invalid range in ``[]``).
        if not re.match(r"^[a-z0-9][a-z0-9._/:@+-]{0,253}$", ref, re.I):
            raise ValueError("image_ref_invalid")
    notes = str(row.get("notes") or "")[:4000]
    image_semver = ""
    if kind == "image":
        raw_sem = str(row.get("image_semver") or "").strip()
        if raw_sem:
            if len(raw_sem) > 64 or not re.match(r"^[a-zA-Z0-9._+v~-]+$", raw_sem):
                raise ValueError("image_semver_invalid")
            image_semver = raw_sem
    elif str(row.get("image_semver") or "").strip():
        raise ValueError("image_semver_only_for_image_kind")
    out: dict[str, Any] = {
        "id": rid,
        "title": title,
        "kind": kind,
        "ref": ref,
        "notes": notes,
    }
    if image_semver:
        out["image_semver"] = image_semver
    return out


def save_requirement_templates(data_dir: Path, doc: dict[str, Any]) -> None:
    ensure_template_layout(data_dir)
    if int(doc.get("version") or 1) < 1:
        raise ValueError("invalid_template_doc_version")
    templates = doc.get("templates")
    if not isinstance(templates, list):
        raise ValueError("templates_must_be_list")
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for row in templates:
        if not isinstance(row, dict):
            continue
        v = validate_template_row(data_dir, row)
        if v["id"] in seen:
            raise ValueError("duplicate_template_id")
        seen.add(v["id"])
        clean.append(v)
    out = {"version": int(doc.get("version") or 1), "templates": clean}
    _write_json_atomic(requirement_templates_file(data_dir), out)


def template_by_id(data_dir: Path, rid: str) -> dict[str, Any] | None:
    doc = load_requirement_templates(data_dir)
    rid = validate_requirement_id(rid)
    for t in doc.get("templates", []):
        if isinstance(t, dict) and str(t.get("id")) == rid:
            return t
    return None


def bundle_fingerprint(data_dir: Path, requirement_ids: list[str]) -> tuple[str, str]:
    """
    Return (cache_key, fingerprint_hex) for sorted unique requirement ids.
    Fingerprint includes template row content so Dockerfile edits invalidate cache.
    """
    ids = sorted({validate_requirement_id(x) for x in requirement_ids if str(x).strip()})
    if not ids:
        raise ValueError("requirements_empty")
    parts: list[str] = []
    for rid in ids:
        t = template_by_id(data_dir, rid)
        if t is None:
            raise ValueError(f"unknown_requirement:{rid}")
        kind = str(t.get("kind") or "")
        ref = str(t.get("ref") or "")
        if kind == "dockerfile":
            p = _safe_ref_path(data_dir, ref)
            try:
                body = p.read_bytes()
            except OSError as e:
                raise ValueError(f"dockerfile_unreadable:{rid}") from e
            h = hashlib.sha256(body).hexdigest()
            parts.append(f"{rid}:dockerfile:{h}")
        else:
            sem = str(t.get("image_semver") or "").strip()
            parts.append(f"{rid}:image:{ref}:{sem}")
    blob = "\n".join(parts).encode("utf-8")
    fp = hashlib.sha256(blob).hexdigest()
    key = "bundle_" + fp[:24]
    return key, fp


