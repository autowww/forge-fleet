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
from pathlib import Path
from typing import Any

_REQ_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

_BUILD_LOCK = threading.Lock()
_BUILD_STATE: dict[str, Any] = {"last_build": None, "in_progress": False}

DEFAULT_REQUIREMENT_TEMPLATES: dict[str, Any] = {
    "version": 1,
    "templates": [],
}

# Matches forge-certificators default Fleet template resolution when using stock worker image.
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


_SEEDING_BUILTIN_CERTIFICATOR_TEMPLATE = False

# Old stock Dockerfile pip-installed forge-certificators from GitHub; Fleet never passed
# FORGE_CERTIFICATORS_GIT_REF, and upgrades did not overwrite an existing seeded file.
_DEPRECATED_BUILTIN_SOURCE_INGEST_MARKERS: tuple[bytes, ...] = (
    b"FORGE_CERTIFICATORS_GIT_REF",
    b"git+https://github.com/autowww/forge-certificators",
)


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _builtin_source_ingest_worker_files_need_resync(dest_df: Path, pkg_df: Path) -> bool:
    """True when the on-disk builtin Dockerfile should be replaced from the packaged copy."""
    if not pkg_df.is_file():
        return False
    if not dest_df.is_file():
        return True
    try:
        body = dest_df.read_bytes()
    except OSError:
        return True
    for marker in _DEPRECATED_BUILTIN_SOURCE_INGEST_MARKERS:
        if marker in body:
            return True
    dest_h = _sha256_file(dest_df)
    pkg_h = _sha256_file(pkg_df)
    if dest_h is None:
        return True
    return pkg_h is not None and dest_h != pkg_h


def ensure_template_layout(data_dir: Path) -> None:
    data_dir = data_dir.resolve()
    rt = requirement_templates_file(data_dir)
    if not rt.is_file():
        _write_json_atomic(rt, DEFAULT_REQUIREMENT_TEMPLATES)
    bc = build_cache_file(data_dir)
    if not bc.is_file():
        _write_json_atomic(bc, DEFAULT_BUILD_CACHE)
    (dockerfiles_allow_root(data_dir) / "dockerfiles").mkdir(parents=True, exist_ok=True)
    seed_builtin_certificator_source_ingest_worker(data_dir)


def seed_builtin_certificator_source_ingest_worker(data_dir: Path) -> None:
    """
    Copy stock source-ingest worker Dockerfile (and vendored worker shim) into
    ``etc/containers/dockerfiles/certificator_source_ingest_worker/`` and register requirement
    template ``certificator_source_ingest_worker`` when absent.

    When the on-disk Dockerfile already exists, it is **re-copied** from the package if the
    bundled file changed (SHA-256 mismatch) or if it still contains deprecated markers from the
    pre-workspace-upload design (git-based ``pip install`` of forge-certificators).

    Skipped when ``FLEET_NO_BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE`` is truthy, or when the
    packaged Dockerfile is missing (broken install).
    """
    global _SEEDING_BUILTIN_CERTIFICATOR_TEMPLATE
    if _SEEDING_BUILTIN_CERTIFICATOR_TEMPLATE:
        return
    if str(os.environ.get("FLEET_NO_BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    data_dir = data_dir.resolve()
    rid = BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE_ID
    root = dockerfiles_allow_root(data_dir)
    dest_dir = root / "dockerfiles" / rid
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_df = dest_dir / "Dockerfile"
    pkg_dir = Path(__file__).resolve().parent / "bundled_certificator_templates" / rid
    pkg_df = pkg_dir / "Dockerfile"
    pkg_worker = pkg_dir / "fleet_source_ingest_worker.py"
    dest_worker = dest_dir / "fleet_source_ingest_worker.py"
    if not pkg_df.is_file():
        return
    if _builtin_source_ingest_worker_files_need_resync(dest_df, pkg_df):
        try:
            shutil.copyfile(pkg_df, dest_df)
            if pkg_worker.is_file():
                shutil.copyfile(pkg_worker, dest_worker)
        except OSError:
            return
    if not dest_df.is_file():
        return
    if pkg_worker.is_file() and not dest_worker.is_file():
        try:
            shutil.copyfile(pkg_worker, dest_worker)
        except OSError:
            pass
    p = requirement_templates_file(data_dir)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        doc = copy.deepcopy(DEFAULT_REQUIREMENT_TEMPLATES)
    if not isinstance(doc, dict):
        doc = copy.deepcopy(DEFAULT_REQUIREMENT_TEMPLATES)
    templates = doc.get("templates")
    if not isinstance(templates, list):
        templates = []
    for row in templates:
        if isinstance(row, dict) and str(row.get("id")) == rid:
            return
    ref = f"dockerfiles/{rid}/Dockerfile"
    try:
        row = validate_template_row(
            data_dir,
            {
                "id": rid,
                "title": "Certificator source-ingest worker (builtin)",
                "kind": "dockerfile",
                "ref": ref,
                "notes": (
                    "Seeded by forge-fleet; slim image (PyPI wheels + vendored worker shim). "
                    "Certificator ships ``src/`` in PUT …/workspace tarball (manifest digest). "
                    "Needs build network (pip + Playwright). Disable with "
                    "FLEET_NO_BUILTIN_CERTIFICATOR_SOURCE_INGEST_TEMPLATE=1 or override via "
                    "PUT /v1/container-templates."
                ),
            },
        )
    except ValueError:
        return
    clean_templates = [t for t in templates if isinstance(t, dict)]
    clean_templates.append(row)
    out_doc = {"version": int(doc.get("version") or 1), "templates": clean_templates}
    _SEEDING_BUILTIN_CERTIFICATOR_TEMPLATE = True
    try:
        save_requirement_templates(data_dir, out_doc)
    finally:
        _SEEDING_BUILTIN_CERTIFICATOR_TEMPLATE = False


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
            built = run_template_build(data_dir, [rid])
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
