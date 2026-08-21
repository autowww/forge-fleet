"""Migration session lifecycle, bundle upload, manifest parsing, step runners."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from fleet_server import migration_jobs, runner, store, workspace_bundle

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

_DEFAULT_MAX_MIGRATION_UPLOAD = 500 * 1024 * 1024


def max_migration_bundle_upload_bytes() -> int:
    raw = str(os.environ.get("FLEET_MIGRATION_BUNDLE_UPLOAD_MAX_BYTES") or "").strip()
    if not raw:
        return _DEFAULT_MAX_MIGRATION_UPLOAD
    try:
        return max(1_048_576, int(raw, 10))
    except ValueError:
        return _DEFAULT_MAX_MIGRATION_UPLOAD


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
    if ver != 1:
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
    if k == "seed_corpus_volume" and not (flags.get("corpus") or flags.get("wiki")):
        return "manifest_flags_no_corpus_or_wiki"
    if k == "migrate_db" and not (flags.get("raw_sec") or flags.get("broker")):
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
    data: bytes,
    *,
    data_dir: Path,
    migration_id: str,
) -> tuple[int, str, str | None, dict[str, Any] | None]:
    """
    Extract tarball bytes into ``migration-bundles/{id}/extracted``.

    Returns ``(uncompressed_bytes, sha256_hex, error_or_none, manifest_or_none)``.
    """
    prof = migration_profile()
    jdir = migration_bundle_dir(data_dir, migration_id)
    if jdir.exists():
        shutil.rmtree(jdir, ignore_errors=True)
    ext_root = jdir / "extracted"
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / "upload.raw").write_bytes(data)
    sha_body = hashlib.sha256(data).hexdigest()

    err = workspace_bundle.extract_tarball_bytes_to_directory(
        data,
        ext_root,
        max_uncompressed_bytes=int(prof.get("max_uncompressed_bytes") or 2 * 1024 * 1024 * 1024),
        max_files=int(prof.get("max_files") or 200_000),
        max_path_depth=int(prof.get("max_path_depth") or 50),
    )
    if err:
        shutil.rmtree(jdir, ignore_errors=True)
        return 0, sha_body, err, None

    manifest, m_err = parse_migration_manifest(ext_root)
    if m_err:
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
    Handle ``PUT /v1/migrations/{id}/data-bundle`` body.

    Returns ``(success_payload, error_response)`` — one is always None.
    """
    row = store.get_migration(conn, migration_id)
    if row is None:
        return None, {"ok": False, "error": "not_found"}
    st = str(row.get("status") or "")
    if st in ("cancelled", "completed"):
        return None, {"ok": False, "error": "migration_terminal"}
    if str(row.get("bundle_state") or "") == "ready":
        return None, {"ok": False, "error": "bundle_already_uploaded"}

    unc, sha256_hex, err, manifest = extract_migration_bundle(
        raw, data_dir=data_dir, migration_id=migration_id
    )
    if err:
        return None, {"ok": False, "error": "extract_failed", "detail": err}

    patch: dict[str, Any] = {
        "bundle_state": "ready",
        "bundle_sha256": sha256_hex,
        "bundle_upload_bytes": len(raw),
        "bundle_uncompressed_bytes": unc,
        "bytes_transferred": int(row.get("bytes_transferred") or 0) + len(raw),
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


def cancel_migration_session(conn: Any, db_path: Path, migration_id: str) -> dict[str, Any]:
    row = store.get_migration(conn, migration_id)
    if row is None:
        return {"ok": False, "error": "not_found"}
    st = str(row.get("status") or "")
    if st in ("cancelled", "completed"):
        return {"ok": True, "status": st, "already_terminal": True}

    for step in row.get("steps") if isinstance(row.get("steps"), list) else []:
        jid = str(step.get("job_id") or "").strip()
        step_st = str(step.get("status") or "")
        if jid and step_st in ("queued", "running"):
            runner.cancel(jid)
            store.update_step(conn, str(step["id"]), status="cancelled")
        elif step_st == "pending":
            store.update_step(conn, str(step["id"]), status="cancelled")

    store.update_migration(conn, migration_id, status="cancelled")
    return {"ok": True, "status": "cancelled"}


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
    step_meta = dict(step.get("meta") or {}) if isinstance(step.get("meta"), dict) else {}
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


def sync_step_from_job(conn: Any, job_row: dict[str, Any]) -> None:
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
        _maybe_finalize_migration(conn, migration_id)


def _maybe_finalize_migration(conn: Any, migration_id: str) -> None:
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
