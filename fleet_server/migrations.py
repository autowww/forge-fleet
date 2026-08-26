"""Migration session lifecycle, bundle upload, manifest parsing, step runners."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from fleet_server import migration_bundle_limits, migration_jobs, runner, store, workspace_bundle

MIGRATION_MANIFEST_FILENAME = ".forge_migration_manifest.json"

DEFAULT_STEP_SEQUENCE: tuple[str, ...] = (
    "restore_from_bundle",
    "seed_corpus_volume",
    "migrate_db",
    "build_image",
    "deploy_service",
    "register_edge_route",
)

_FLAG_TO_STEP: dict[str, str] = {
    "corpus": "seed_corpus_volume",
    "raw_sec": "migrate_db",
    "broker": "migrate_db",
    "wiki": "seed_corpus_volume",
}

_DEFAULT_MAX_MIGRATION_UPLOAD = migration_bundle_limits._DEFAULT_GLOBAL_MAX_BYTES
_DEFAULT_CHUNK_SIZE_BYTES = 64 * 1024 * 1024


def default_chunk_size_bytes() -> int:
    raw = str(os.environ.get("FLEET_MIGRATION_CHUNK_SIZE_BYTES") or "").strip()
    if not raw:
        return _DEFAULT_CHUNK_SIZE_BYTES
    try:
        return max(1_048_576, int(raw, 10))
    except ValueError:
        return _DEFAULT_CHUNK_SIZE_BYTES


def max_chunk_upload_bytes() -> int:
    return default_chunk_size_bytes() + (1024 * 1024)


def _upload_session_path(data_dir: Path, migration_id: str) -> Path:
    return migration_bundle_dir(data_dir, migration_id) / "upload-session.json"


def _chunks_dir(data_dir: Path, migration_id: str) -> Path:
    return migration_bundle_dir(data_dir, migration_id) / "chunks"


def _load_upload_session(data_dir: Path, migration_id: str) -> dict[str, Any] | None:
    path = _upload_session_path(data_dir, migration_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _save_upload_session(data_dir: Path, migration_id: str, session: dict[str, Any]) -> None:
    jdir = migration_bundle_dir(data_dir, migration_id)
    jdir.mkdir(parents=True, exist_ok=True)
    _upload_session_path(data_dir, migration_id).write_text(
        json.dumps(session, separators=(",", ":")),
        encoding="utf-8",
    )


_EXTRACT_STEP_KINDS = {"seed_corpus_volume", "migrate_db", "restore_from_bundle"}
_SCRATCH_ACTIVE_STEPS = {"pending", "queued", "running", "failed"}
_EXTRACT_BLOCKING_STEPS = {"pending", "queued", "running"}
_DEFAULT_SCRATCH_RETENTION_HOURS = 24.0
_DEFAULT_ABANDONED_HOURS = 24.0


def migration_scratch_retention_hours() -> float:
    raw = str(os.environ.get("FLEET_MIGRATION_SCRATCH_RETENTION_HOURS") or "").strip()
    if not raw:
        return _DEFAULT_SCRATCH_RETENTION_HOURS
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _DEFAULT_SCRATCH_RETENTION_HOURS


def migration_abandoned_hours() -> float:
    raw = str(os.environ.get("FLEET_MIGRATION_ABANDONED_HOURS") or "").strip()
    if not raw:
        return _DEFAULT_ABANDONED_HOURS
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _DEFAULT_ABANDONED_HOURS


def _dir_bytes(root: Path) -> int:
    return _sum_extracted_bytes(root) if root.is_dir() else 0


def purge_migration_scratch(data_dir: Path, migration_id: str) -> int:
    """Delete chunk files, assembled archive, and extracted tree for one session."""
    jdir = migration_bundle_dir(data_dir, migration_id)
    if not jdir.is_dir():
        return 0
    freed = _dir_bytes(jdir)
    shutil.rmtree(jdir, ignore_errors=True)
    return freed


def _clear_chunk_upload_state(data_dir: Path, migration_id: str) -> None:
    purge_migration_scratch(data_dir, migration_id)


def _extract_steps_matching(row: dict[str, Any], statuses: set[str]) -> list[dict[str, Any]]:
    steps = row.get("steps") if isinstance(row.get("steps"), list) else []
    out: list[dict[str, Any]] = []
    for step in steps:
        if str(step.get("kind") or "") not in _EXTRACT_STEP_KINDS:
            continue
        if str(step.get("status") or "") in statuses:
            out.append(step)
    return out


def migration_scratch_needed(row: dict[str, Any] | None) -> bool:
    """True when chunk/extracted files are still required for upload or extract steps."""
    if row is None:
        return False
    status = str(row.get("status") or "")
    if status in {"cancelled", "completed", "failed"}:
        if _extract_steps_matching(row, _EXTRACT_BLOCKING_STEPS):
            return True
        return False
    if str(row.get("bundle_state") or "") == "uploading":
        return True
    if _extract_steps_matching(row, _SCRATCH_ACTIVE_STEPS):
        return True
    return False


def _step_age_seconds(step: dict[str, Any], now: float) -> float:
    updated = float(step.get("updated") or step.get("created") or 0)
    if updated <= 0:
        return 0.0
    return max(0.0, now - updated)


def _migration_age_seconds(row: dict[str, Any], now: float) -> float:
    updated = float(row.get("updated") or row.get("created") or 0)
    if updated <= 0:
        return 0.0
    return max(0.0, now - updated)


def _scratch_gc_reason(
    row: dict[str, Any] | None,
    *,
    now: float,
    retention_seconds: float,
    abandoned_seconds: float,
) -> str | None:
    """Return purge reason when scratch dir should be removed, else None."""
    if row is None:
        return "orphan"
    status = str(row.get("status") or "")
    bundle_state = str(row.get("bundle_state") or "")

    if status in {"cancelled", "completed", "failed"}:
        if not _extract_steps_matching(row, _EXTRACT_BLOCKING_STEPS):
            return f"terminal_{status}"
        failed_extract = _extract_steps_matching(row, {"failed"})
        if failed_extract and all(_step_age_seconds(s, now) >= retention_seconds for s in failed_extract):
            return "failed_extract_retention"
        return None

    if bundle_state == "uploading":
        return None

    blocking = _extract_steps_matching(row, _EXTRACT_BLOCKING_STEPS)
    if blocking:
        if all(_step_age_seconds(s, now) >= abandoned_seconds for s in blocking):
            return "abandoned_extract"
        return None

    failed_extract = _extract_steps_matching(row, {"failed"})
    if failed_extract:
        if all(_step_age_seconds(s, now) >= retention_seconds for s in failed_extract):
            return "failed_extract_retention"
        return None

    if bundle_state == "ready" and status in {"active", "pending"} and _migration_age_seconds(row, now) >= abandoned_seconds:
        return "abandoned_ready"

    if not migration_scratch_needed(row):
        return "idle_scratch"

    return None


def maybe_purge_migration_scratch(conn: Any, data_dir: Path, migration_id: str) -> int:
    row = store.get_migration(conn, migration_id)
    if migration_scratch_needed(row):
        return 0
    return purge_migration_scratch(data_dir, migration_id)


def gc_stale_migration_scratch(
    data_dir: Path,
    db_path: Path,
    *,
    dry_run: bool = False,
    retention_hours: float | None = None,
    abandoned_hours: float | None = None,
) -> dict[str, Any]:
    """Remove migration bundle scratch dirs that are terminal, orphaned, or past retention TTL."""
    retention_seconds = (retention_hours if retention_hours is not None else migration_scratch_retention_hours()) * 3600.0
    abandoned_seconds = (abandoned_hours if abandoned_hours is not None else migration_abandoned_hours()) * 3600.0
    root = data_dir / "migration-bundles"
    purged: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    bytes_freed = 0
    if not root.is_dir():
        return {
            "ok": True,
            "dry_run": dry_run,
            "purged": purged,
            "kept": kept,
            "bytes_freed": 0,
            "retention_hours": retention_seconds / 3600.0,
            "abandoned_hours": abandoned_seconds / 3600.0,
        }

    conn = store.connect(db_path)
    try:
        now = time.time()
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            mid = child.name
            row = store.get_migration(conn, mid)
            reason = _scratch_gc_reason(
                row,
                now=now,
                retention_seconds=retention_seconds,
                abandoned_seconds=abandoned_seconds,
            )
            if reason is None:
                kept.append(
                    {
                        "id": mid,
                        "status": str((row or {}).get("status") or "unknown"),
                        "bundle_state": str((row or {}).get("bundle_state") or ""),
                    }
                )
                continue
            freed = _dir_bytes(child)
            if not dry_run:
                shutil.rmtree(child, ignore_errors=True)
            if dry_run or not child.exists():
                bytes_freed += freed
                purged.append(
                    {
                        "id": mid,
                        "status": str((row or {}).get("status") or "missing"),
                        "reason": reason,
                        "bytes_freed": freed,
                    }
                )
    finally:
        conn.close()

    return {
        "ok": True,
        "dry_run": dry_run,
        "purged": purged,
        "kept": kept,
        "bytes_freed": bytes_freed,
        "retention_hours": retention_seconds / 3600.0,
        "abandoned_hours": abandoned_seconds / 3600.0,
    }


def purge_idle_migration_scratch(conn: Any, data_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Remove leftover Market/Fleet bundle chunks after cancel, complete, or skipped extract steps."""
    _ = conn
    return gc_stale_migration_scratch(data_dir, data_dir / "fleet.sqlite", dry_run=dry_run)


def _migration_upload_guard(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return {"ok": False, "error": "not_found"}
    st = str(row.get("status") or "")
    if st in ("cancelled", "completed"):
        return {"ok": False, "error": "migration_terminal"}
    if str(row.get("bundle_state") or "") == "ready":
        return {"ok": False, "error": "bundle_already_uploaded"}
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            buf = fh.read(1024 * 1024)
            if not buf:
                break
            digest.update(buf)
    return digest.hexdigest()


def _extract_error_payload(err: str, row: dict[str, Any] | None) -> dict[str, Any]:
    token = str(err or "extract_failed").split(":", 1)[0]
    payload: dict[str, Any] = {
        "ok": False,
        "error": "extract_failed",
        "detail": err,
        "recovery_code": token,
    }
    if token == "uncompressed_size_exceeded":
        payload["max_uncompressed_bytes"] = migration_bundle_limits.max_bundle_uncompressed_bytes(row)
    if token == "too_many_files":
        payload["max_files"] = migration_bundle_limits.max_bundle_files(row)
    return payload


def _complete_bundle_upload(
    conn: Any,
    db_path: Path,
    data_dir: Path,
    migration_id: str,
    raw: bytes | None = None,
    *,
    archive_path: Path | None = None,
    sha256_hex: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    row = store.get_migration(conn, migration_id)
    guard = _migration_upload_guard(row)
    if guard:
        return None, guard

    unc, sha256_out, err, manifest = extract_migration_bundle(
        raw,
        archive_path=archive_path,
        data_dir=data_dir,
        migration_id=migration_id,
        migration_row=row,
        sha256_hex=sha256_hex,
    )
    if err:
        return None, _extract_error_payload(err, row)

    if archive_path is not None:
        upload_len = int(archive_path.stat().st_size)
    else:
        upload_len = len(raw or b"")

    st = str(row.get("status") or "")
    patch: dict[str, Any] = {
        "bundle_state": "ready",
        "bundle_sha256": sha256_out,
        "bundle_upload_bytes": upload_len,
        "bundle_uncompressed_bytes": unc,
        "bytes_transferred": int(row.get("bytes_transferred") or 0) + upload_len,
        "manifest": manifest,
    }
    if st == "pending":
        patch["status"] = "active"
    store.update_migration(conn, migration_id, **patch)
    if manifest:
        apply_manifest_to_steps(conn, migration_id, manifest)

    updated = store.get_migration(conn, migration_id)
    payload = public_migration_payload(updated) if updated else {"id": migration_id}
    payload["ok"] = True
    return payload, None


def max_migration_bundle_upload_bytes(migration_row: dict[str, Any] | None = None) -> int:
    return migration_bundle_limits.max_bundle_upload_bytes(migration_row)


def migration_bundle_dir(data_dir: Path, migration_id: str) -> Path:
    return (data_dir / "migration-bundles" / migration_id).resolve()


def bundle_extracted_root(data_dir: Path, migration_id: str) -> Path:
    return migration_bundle_dir(data_dir, migration_id) / "extracted"


def migration_profile() -> dict[str, Any]:
    prof = dict(workspace_bundle.WORKSPACE_PROFILES["migration_bundle"])
    prof["profile_id"] = "migration_bundle"
    return prof


def parse_migration_manifest(ext_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    """
    Parse ``.forge_migration_manifest.json`` from an extracted bundle tree.

    Returns ``(manifest_dict, error_or_none)``.
    """
    path = ext_root / MIGRATION_MANIFEST_FILENAME
    if not path.is_file():
        return None, "manifest_required_but_missing"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        return None, f"invalid_manifest_json:{ex}"
    if not isinstance(doc, dict):
        return None, "manifest_not_object"
    ver = doc.get("schema_version")
    if ver not in (1, 2):
        return None, f"unsupported_schema_version:{ver!r}"
    flags = doc.get("flags")
    if flags is None:
        flags = {}
    if not isinstance(flags, dict):
        return None, "flags_not_object"
    normalized_flags = {
        "corpus": bool(flags.get("corpus")),
        "raw_sec": bool(flags.get("raw_sec")),
        "broker": bool(flags.get("broker")),
        "wiki": bool(flags.get("wiki")),
        "database": bool(flags.get("database")),
    }
    out: dict[str, Any] = {
        "schema_version": 1,
        "flags": normalized_flags,
    }
    if isinstance(doc.get("files"), list):
        out["files"] = doc["files"]
    if isinstance(doc.get("inventory_bytes"), (int, float)):
        out["inventory_bytes"] = int(doc["inventory_bytes"])
    return out, None


def _flag_skip_reason(kind: str, flags: dict[str, bool]) -> str | None:
    """Return a skip reason when manifest flags say this step is not needed."""
    k = str(kind)
    if k == "restore_from_bundle":
        return None
    if k == "seed_corpus_volume":
        return None
    if k == "migrate_db" and not (
        flags.get("database") or flags.get("raw_sec") or flags.get("broker")
    ):
        return "manifest_flags_no_db_payload"
    if k in ("build_image", "deploy_service", "register_edge_route"):
        return None
    return None


def apply_manifest_to_steps(
    conn: Any,
    migration_id: str,
    manifest: dict[str, Any],
) -> None:
    flags = manifest.get("flags") if isinstance(manifest.get("flags"), dict) else {}
    steps = store.list_migration_steps(conn, migration_id)
    for step in steps:
        kind = str(step.get("kind") or "")
        reason = _flag_skip_reason(kind, flags)
        if reason and str(step.get("status") or "") == "pending":
            store.update_step(
                conn,
                str(step["id"]),
                status="skipped",
                meta_patch={"skip_reason": reason},
            )


def extract_migration_bundle(
    data: bytes | None = None,
    *,
    archive_path: Path | None = None,
    data_dir: Path,
    migration_id: str,
    migration_row: dict[str, Any] | None = None,
    sha256_hex: str | None = None,
) -> tuple[int, str, str | None, dict[str, Any] | None]:
    """
    Extract a tarball into ``migration-bundles/{id}/extracted``.

    Pass either in-memory ``data`` (small/single-shot uploads) or ``archive_path``
    (chunked Market bundles) so Granite does not buffer multi-gigabyte archives.

    Returns ``(uncompressed_bytes, sha256_hex, error_or_none, manifest_or_none)``.
    """
    if (data is None) == (archive_path is None):
        return 0, "", "extract_input_invalid", None

    prof = migration_profile()
    max_unc = migration_bundle_limits.max_bundle_uncompressed_bytes(migration_row)
    max_files = migration_bundle_limits.max_bundle_files(migration_row)
    max_depth = int(prof.get("max_path_depth") or 50)
    jdir = migration_bundle_dir(data_dir, migration_id)
    ext_root = jdir / "extracted"
    jdir.mkdir(parents=True, exist_ok=True)

    if archive_path is not None:
        if ext_root.exists():
            shutil.rmtree(ext_root, ignore_errors=True)
        sha_body = sha256_hex or _sha256_file(archive_path)
        err = workspace_bundle.extract_tarball_path_to_directory(
            archive_path,
            ext_root,
            max_uncompressed_bytes=max_unc,
            max_files=max_files,
            max_path_depth=max_depth,
        )
        if err:
            shutil.rmtree(ext_root, ignore_errors=True)
            return 0, sha_body, err, None
    else:
        if jdir.exists():
            shutil.rmtree(jdir, ignore_errors=True)
        jdir.mkdir(parents=True, exist_ok=True)
        blob = data or b""
        (jdir / "upload.raw").write_bytes(blob)
        sha_body = hashlib.sha256(blob).hexdigest()
        err = workspace_bundle.extract_tarball_bytes_to_directory(
            blob,
            ext_root,
            max_uncompressed_bytes=max_unc,
            max_files=max_files,
            max_path_depth=max_depth,
        )
        if err:
            shutil.rmtree(jdir, ignore_errors=True)
            return 0, sha_body, err, None

    manifest, m_err = parse_migration_manifest(ext_root)
    if m_err:
        shutil.rmtree(ext_root, ignore_errors=True)
        if data is not None:
            shutil.rmtree(jdir, ignore_errors=True)
        return 0, sha_body, m_err, None
    return _sum_extracted_bytes(ext_root), sha_body, None, manifest


def _sum_extracted_bytes(ext_root: Path) -> int:
    total = 0
    if not ext_root.is_dir():
        return 0
    for p in ext_root.rglob("*"):
        if p.is_file():
            try:
                total += int(p.stat().st_size)
            except OSError:
                pass
    return total


def create_migration_session(
    conn: Any,
    *,
    source_label: str = "",
    target_label: str = "",
    meta: dict[str, Any] | None = None,
    include_restore_step: bool = False,
) -> dict[str, Any]:
    """Create migration row + default pending steps."""
    step_kinds = list(DEFAULT_STEP_SEQUENCE)
    if not include_restore_step:
        step_kinds = [k for k in step_kinds if k != "restore_from_bundle"]
    mid = store.create_migration(
        conn,
        source_label=source_label,
        target_label=target_label,
        meta=meta,
        step_kinds=step_kinds,
    )
    row = store.get_migration(conn, mid)
    return public_migration_payload(row) if row else {"id": mid}


def public_migration_payload(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe migration + steps for API responses."""
    steps_out: list[dict[str, Any]] = []
    for s in row.get("steps") if isinstance(row.get("steps"), list) else []:
        sm = dict(s.get("meta") or {}) if isinstance(s.get("meta"), dict) else {}
        steps_out.append(
            {
                "id": s.get("id"),
                "kind": s.get("kind"),
                "status": s.get("status"),
                "job_id": s.get("job_id"),
                "sort_order": s.get("sort_order"),
                "meta": sm,
                "created": s.get("created"),
                "updated": s.get("updated"),
            }
        )
    manifest = row.get("manifest") if isinstance(row.get("manifest"), dict) else None
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "source_label": row.get("source_label") or "",
        "target_label": row.get("target_label") or "",
        "bundle_state": row.get("bundle_state") or "pending_upload",
        "bundle_sha256": row.get("bundle_sha256"),
        "bundle_upload_bytes": row.get("bundle_upload_bytes"),
        "bundle_uncompressed_bytes": row.get("bundle_uncompressed_bytes"),
        "bytes_transferred": row.get("bytes_transferred") or 0,
        "manifest": manifest,
        "meta": dict(row.get("meta") or {}) if isinstance(row.get("meta"), dict) else {},
        "bundle_upload_max_bytes": max_migration_bundle_upload_bytes(row),
        "bundle_uncompressed_max_bytes": migration_bundle_limits.max_bundle_uncompressed_bytes(row),
        "bundle_max_files": migration_bundle_limits.max_bundle_files(row),
        "steps": steps_out,
        "created": row.get("created"),
        "updated": row.get("updated"),
    }


def upload_data_bundle(
    conn: Any,
    db_path: Path,
    data_dir: Path,
    migration_id: str,
    raw: bytes,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """
    Handle ``PUT /v1/migrations/{id}/data-bundle`` body (single-shot upload).

    Returns ``(success_payload, error_response)`` — one is always None.
    """
    session = _load_upload_session(data_dir, migration_id)
    if session is not None:
        return None, {
            "ok": False,
            "error": "chunked_upload_in_progress",
            "detail": "finish chunked upload via POST …/data-bundle/finalize",
        }
    return _complete_bundle_upload(conn, db_path, data_dir, migration_id, raw)


def start_bundle_upload_session(
    conn: Any,
    data_dir: Path,
    migration_id: str,
    *,
    sha256: str,
    total_bytes: int,
    chunk_size: int | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Begin a chunked bundle upload session."""
    row = store.get_migration(conn, migration_id)
    guard = _migration_upload_guard(row)
    if guard:
        return None, guard

    digest = str(sha256 or "").strip().lower()
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        return None, {"ok": False, "error": "invalid_body", "detail": "sha256 must be 64 hex chars"}
    try:
        total = int(total_bytes)
    except (TypeError, ValueError):
        return None, {"ok": False, "error": "invalid_body", "detail": "total_bytes must be a positive integer"}
    if total <= 0:
        return None, {"ok": False, "error": "invalid_body", "detail": "total_bytes must be > 0"}
    max_up = max_migration_bundle_upload_bytes(row)
    if total > max_up:
        return None, {
            "ok": False,
            "error": "bundle_too_large",
            "detail": f"total_bytes {total} exceeds max {max_up}",
            "recovery_code": "bundle_too_large",
            "max_upload_bytes": max_up,
        }

    size = int(chunk_size or default_chunk_size_bytes())
    if size <= 0 or size > max_chunk_upload_bytes():
        return None, {"ok": False, "error": "invalid_body", "detail": "chunk_size out of range"}

    chunk_count = (total + size - 1) // size

    existing = _load_upload_session(data_dir, migration_id)
    if existing is not None:
        existing_digest = str(existing.get("sha256") or "").strip().lower()
        existing_total = int(existing.get("total_bytes") or 0)
        existing_size = int(existing.get("chunk_size") or size)
        if existing_digest == digest and existing_total == total:
            if existing_size != size:
                return None, {
                    "ok": False,
                    "error": "chunk_size_mismatch",
                    "detail": "resume requires the same chunk_size as the prior session",
                }
            received = sorted({int(x) for x in (existing.get("received") or [])})
            chunks_dir = _chunks_dir(data_dir, migration_id)
            chunks_dir.mkdir(parents=True, exist_ok=True)
            store.update_migration(conn, migration_id, bundle_state="uploading")
            return (
                {
                    "ok": True,
                    "migration_id": migration_id,
                    "sha256": digest,
                    "total_bytes": total,
                    "chunk_size": size,
                    "chunk_count": chunk_count,
                    "bundle_state": "uploading",
                    "resumed": True,
                    "received": received,
                },
                None,
            )
        _clear_chunk_upload_state(data_dir, migration_id)

    chunks_dir = _chunks_dir(data_dir, migration_id)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    session_doc = {
        "sha256": digest,
        "total_bytes": total,
        "chunk_size": size,
        "chunk_count": chunk_count,
        "received": [],
        "created": time.time(),
    }
    _save_upload_session(data_dir, migration_id, session_doc)
    store.update_migration(conn, migration_id, bundle_state="uploading")

    return (
        {
            "ok": True,
            "migration_id": migration_id,
            "sha256": digest,
            "total_bytes": total,
            "chunk_size": size,
            "chunk_count": chunk_count,
            "bundle_state": "uploading",
        },
        None,
    )


def upload_bundle_chunk(
    conn: Any,
    data_dir: Path,
    migration_id: str,
    chunk_index: int,
    raw: bytes,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Store one chunk for an in-progress upload session."""
    row = store.get_migration(conn, migration_id)
    guard = _migration_upload_guard(row)
    if guard:
        return None, guard

    session = _load_upload_session(data_dir, migration_id)
    if session is None:
        return None, {"ok": False, "error": "upload_session_missing"}

    try:
        idx = int(chunk_index)
    except (TypeError, ValueError):
        return None, {"ok": False, "error": "invalid_chunk_index"}
    chunk_count = int(session.get("chunk_count") or 0)
    if idx < 0 or idx >= chunk_count:
        return None, {"ok": False, "error": "invalid_chunk_index"}

    total = int(session.get("total_bytes") or 0)
    size = int(session.get("chunk_size") or default_chunk_size_bytes())
    expected = min(size, total - (idx * size))
    if len(raw) != expected:
        return None, {
            "ok": False,
            "error": "invalid_chunk_size",
            "detail": f"chunk {idx} expected {expected} bytes, got {len(raw)}",
        }

    chunk_path = _chunks_dir(data_dir, migration_id) / f"{idx:06d}"
    chunk_path.write_bytes(raw)

    received = sorted(set(int(x) for x in (session.get("received") or [])) | {idx})
    session["received"] = received
    _save_upload_session(data_dir, migration_id, session)

    bytes_done = sum(
        min(size, total - (i * size))
        for i in received
    )
    return (
        {
            "ok": True,
            "migration_id": migration_id,
            "chunk_index": idx,
            "received_chunks": len(received),
            "chunk_count": chunk_count,
            "bytes_received": bytes_done,
            "total_bytes": total,
        },
        None,
    )


def finalize_chunked_bundle(
    conn: Any,
    db_path: Path,
    data_dir: Path,
    migration_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Assemble uploaded chunks, verify digest, extract bundle."""
    row = store.get_migration(conn, migration_id)
    guard = _migration_upload_guard(row)
    if guard:
        return None, guard

    session = _load_upload_session(data_dir, migration_id)
    if session is None:
        return None, {"ok": False, "error": "upload_session_missing"}

    chunk_count = int(session.get("chunk_count") or 0)
    received = sorted(int(x) for x in (session.get("received") or []))
    if len(received) != chunk_count or received != list(range(chunk_count)):
        missing = [i for i in range(chunk_count) if i not in received]
        return None, {
            "ok": False,
            "error": "chunks_incomplete",
            "detail": f"missing chunk indexes: {missing[:20]}",
            "received_chunks": len(received),
            "chunk_count": chunk_count,
            "recovery_code": "chunks_incomplete",
        }

    chunks_dir = _chunks_dir(data_dir, migration_id)
    jdir = migration_bundle_dir(data_dir, migration_id)
    jdir.mkdir(parents=True, exist_ok=True)
    assembled = jdir / "assembled.bin"
    hasher = hashlib.sha256()
    written = 0
    with assembled.open("wb") as out:
        for idx in range(chunk_count):
            chunk_path = chunks_dir / f"{idx:06d}"
            if not chunk_path.is_file():
                assembled.unlink(missing_ok=True)
                return None, {
                    "ok": False,
                    "error": "chunks_incomplete",
                    "detail": f"missing chunk file {idx}",
                    "recovery_code": "chunks_incomplete",
                }
            with chunk_path.open("rb") as fh:
                while True:
                    buf = fh.read(1024 * 1024)
                    if not buf:
                        break
                    hasher.update(buf)
                    out.write(buf)
                    written += len(buf)

    expected_sha = str(session.get("sha256") or "").lower()
    actual_sha = hasher.hexdigest()
    if actual_sha != expected_sha:
        assembled.unlink(missing_ok=True)
        return None, {
            "ok": False,
            "error": "bundle_sha256_mismatch",
            "detail": "assembled bundle digest does not match upload session sha256",
            "recovery_code": "bundle_sha256_mismatch",
        }
    if written != int(session.get("total_bytes") or 0):
        assembled.unlink(missing_ok=True)
        return None, {
            "ok": False,
            "error": "bundle_size_mismatch",
            "recovery_code": "bundle_size_mismatch",
        }

    shutil.rmtree(chunks_dir, ignore_errors=True)
    ok_payload, err_payload = _complete_bundle_upload(
        conn,
        db_path,
        data_dir,
        migration_id,
        archive_path=assembled,
        sha256_hex=actual_sha,
    )
    assembled.unlink(missing_ok=True)
    if err_payload is None:
        session_path = _upload_session_path(data_dir, migration_id)
        if session_path.is_file():
            session_path.unlink(missing_ok=True)
        if ok_payload is not None:
            ok_payload["upload_mode"] = "chunked"
            ok_payload["chunk_count"] = chunk_count
    return ok_payload, err_payload


def cancel_migration_session(
    conn: Any,
    db_path: Path,
    migration_id: str,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    row = store.get_migration(conn, migration_id)
    if row is None:
        return {"ok": False, "error": "not_found"}
    st = str(row.get("status") or "")
    if st in ("cancelled", "completed"):
        bytes_freed = purge_migration_scratch(data_dir, migration_id) if data_dir is not None else 0
        return {
            "ok": True,
            "status": st,
            "already_terminal": True,
            "bytes_freed": bytes_freed,
        }

    for step in row.get("steps") if isinstance(row.get("steps"), list) else []:
        jid = str(step.get("job_id") or "").strip()
        step_st = str(step.get("status") or "")
        if jid and step_st in ("queued", "running"):
            runner.cancel(jid)
            store.update_step(conn, str(step["id"]), status="cancelled")
        elif step_st == "pending":
            store.update_step(conn, str(step["id"]), status="cancelled")

    store.update_migration(conn, migration_id, status="cancelled")
    bytes_freed = purge_migration_scratch(data_dir, migration_id) if data_dir is not None else 0
    return {"ok": True, "status": "cancelled", "bytes_freed": bytes_freed}


def run_migration_step(
    conn: Any,
    db_path: Path,
    data_dir: Path,
    migration_id: str,
    step_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    row = store.get_migration(conn, migration_id)
    if row is None:
        return None, {"ok": False, "error": "not_found"}
    if str(row.get("status") or "") == "cancelled":
        return None, {"ok": False, "error": "migration_cancelled"}
    if str(row.get("bundle_state") or "") != "ready":
        return None, {"ok": False, "error": "bundle_not_ready"}

    step = None
    for s in row.get("steps") if isinstance(row.get("steps"), list) else []:
        if str(s.get("id")) == step_id:
            step = s
            break
    if step is None:
        return None, {"ok": False, "error": "step_not_found"}

    step_status = str(step.get("status") or "")
    if step_status in ("completed", "skipped"):
        return None, {"ok": False, "error": "step_not_runnable", "detail": step_status}
    if step_status in ("queued", "running"):
        return None, {"ok": False, "error": "step_already_active"}

    kind = str(step.get("kind") or "")
    mig_meta = dict(row.get("meta") or {}) if isinstance(row.get("meta"), dict) else {}
    step_meta = dict(step.get("meta") or {}) if isinstance(step.get("meta"), dict) else {}
    step_meta = {**mig_meta, **step_meta}
    from fleet_server import app_gateway

    if kind == "deploy_service":
        try:
            app_gateway.apply_compose_env(step_meta)
            prep = app_gateway.prepare_compose_app_bearer(step_meta)
        except ValueError as ex:
            return None, {"ok": False, "error": "app_bearer_setup_failed", "detail": str(ex)[:800]}
        if prep.get("generated"):
            step_meta = {**step_meta, "force_recreate": True}

    if kind == "register_edge_route":
        try:
            result = app_gateway.register_from_migration_meta(data_dir, step_meta)
        except ValueError as ex:
            return None, {"ok": False, "error": "gateway_register_failed", "detail": str(ex)[:800]}
        store.update_step(
            conn,
            step_id,
            status="completed",
            meta_patch={"gateway": result, "new_tunnel": False},
        )
        _maybe_finalize_migration(conn, migration_id, data_dir=data_dir)
        return (
            {
                "ok": True,
                "migration_id": migration_id,
                "step_id": step_id,
                "status": "completed",
                "gateway": result,
            },
            None,
        )

    bundle_root = bundle_extracted_root(data_dir, migration_id)
    try:
        argv = migration_jobs.build_argv_for_step(
            kind,
            migration_id=migration_id,
            step_id=step_id,
            bundle_extracted=bundle_root if bundle_root.is_dir() else None,
            meta=step_meta,
        )
    except (ValueError, FileNotFoundError) as ex:
        return None, {"ok": False, "error": "step_argv_failed", "detail": str(ex)[:800]}

    job_meta = migration_jobs.job_meta_for_step(
        migration_id, step_id, kind, step_meta=step_meta
    )
    jid = store.insert_job(
        conn,
        kind="docker_argv",
        argv=argv,
        session_id=f"migration-{migration_id[:12]}",
        meta=job_meta,
    )
    store.update_step(
        conn,
        step_id,
        status="queued",
        job_id=jid,
        meta_patch={"last_run_job_id": jid},
    )
    runner.spawn(db_path, jid)
    return (
        {"ok": True, "migration_id": migration_id, "step_id": step_id, "job_id": jid, "status": "queued"},
        None,
    )


def sync_step_from_job(
    conn: Any,
    job_row: dict[str, Any],
    data_dir: Path | None = None,
) -> None:
    """Advance migration step state when a linked job reaches a terminal status."""
    meta = job_row.get("meta") if isinstance(job_row.get("meta"), dict) else {}
    step_id = str(meta.get("migration_step_id") or "").strip()
    if not step_id:
        return
    job_status = str(job_row.get("status") or "").lower()
    if job_status == "completed":
        store.update_step(conn, step_id, status="completed")
    elif job_status in ("failed", "cancelled"):
        store.update_step(conn, step_id, status=job_status)
    migration_id = str(meta.get("migration_id") or "").strip()
    if migration_id:
        _maybe_finalize_migration(conn, migration_id, data_dir=data_dir)


def _maybe_finalize_migration(
    conn: Any,
    migration_id: str,
    data_dir: Path | None = None,
) -> None:
    row = store.get_migration(conn, migration_id)
    if row is None:
        return
    steps = row.get("steps") if isinstance(row.get("steps"), list) else []
    if not steps:
        return
    terminal = {"completed", "skipped", "failed", "cancelled"}
    if all(str(s.get("status") or "") in terminal for s in steps):
        if any(str(s.get("status") or "") == "failed" for s in steps):
            store.update_migration(conn, migration_id, status="failed")
        elif any(str(s.get("status") or "") == "cancelled" for s in steps):
            store.update_migration(conn, migration_id, status="cancelled")
        else:
            store.update_migration(conn, migration_id, status="completed")
    if data_dir is not None:
        maybe_purge_migration_scratch(conn, data_dir, migration_id)
