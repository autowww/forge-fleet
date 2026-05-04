"""Per-job workspace archives: extract, validate, mount paths, cleanup."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

# Profile id -> container mount point and extraction limits
WORKSPACE_PROFILES: dict[str, dict[str, Any]] = {
    # Larger limits for callers that upload full repo-style trees (selected via meta.workspace_profile only).
    "large_workspace": {
        "container_mount": "/workspace",
        "max_uncompressed_bytes": 500 * 1024 * 1024,
        "max_files": 100_000,
        "max_path_depth": 50,
    },
    "generic": {
        "container_mount": "/workspace",
        "max_uncompressed_bytes": 200 * 1024 * 1024,
        "max_files": 50_000,
        "max_path_depth": 40,
    },
}

_DEFAULT_MAX_UPLOAD_BYTES = 256 * 1024 * 1024

# Top-level member in uploaded workspace archives; lists other files for post-extract digest checks.
WORKSPACE_MANIFEST_FILENAME = ".forge_workspace_manifest.json"


def profile_for_meta(meta: dict[str, Any]) -> dict[str, Any]:
    key = str(meta.get("workspace_profile") or meta.get("container_class") or "generic").strip()
    if key in WORKSPACE_PROFILES:
        base = dict(WORKSPACE_PROFILES[key])
    else:
        base = dict(WORKSPACE_PROFILES["generic"])
    base["profile_id"] = key
    return base


def job_workspace_dir(data_dir: Path, job_id: str) -> Path:
    return (data_dir / "job-workspaces" / job_id).resolve()


def extracted_root(data_dir: Path, job_id: str) -> Path:
    return job_workspace_dir(data_dir, job_id) / "extracted"


def max_upload_bytes() -> int:
    raw = str(os.environ.get("FLEET_WORKSPACE_UPLOAD_MAX_BYTES") or "").strip()
    if not raw:
        return _DEFAULT_MAX_UPLOAD_BYTES
    try:
        return max(1_048_576, int(raw, 10))
    except ValueError:
        return _DEFAULT_MAX_UPLOAD_BYTES


def _safe_member_name(name: str) -> bool:
    n = name.replace("\\", "/").strip("/")
    if not n or n.startswith("..") or "/../" in f"/{n}/":
        return False
    parts = n.split("/")
    if ".." in parts:
        return False
    return True


def _extract_member_safe(tf: tarfile.TarFile, member: tarfile.TarInfo, dest_root: Path) -> None:
    name = member.name.replace("\\", "/").strip("/")
    if not name or not _safe_member_name(name):
        raise OSError("unsafe_path_in_archive")
    dest = (dest_root / name).resolve()
    dest.relative_to(dest_root.resolve())
    if member.isdir():
        dest.mkdir(parents=True, exist_ok=True)
        return
    if member.issym() or member.islnk():
        raise OSError("symlink_not_allowed")
    if not member.isfile():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    reader = tf.extractfile(member)
    if reader is None:
        return
    try:
        with open(dest, "wb") as out_f:
            shutil.copyfileobj(reader, out_f, length=256 * 1024)
    finally:
        reader.close()
    mode = getattr(member, "mode", None)
    if mode is not None:
        try:
            os.chmod(dest, stat.S_IMODE(mode))
        except OSError:
            pass


def verify_extracted_workspace_manifest(
    ext_root: Path, *, manifest_required: bool
) -> tuple[str | None, int, int | None]:
    """
    When ``.forge_workspace_manifest.json`` exists, validate schema and re-hash each listed file.
    Returns ``(error_or_none, files_verified_count, schema_version_or_none)``.
    """
    path = ext_root / WORKSPACE_MANIFEST_FILENAME
    if not path.is_file():
        if manifest_required:
            return "manifest_required_but_missing", 0, None
        return None, 0, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        return f"manifest_verification_failed: invalid_manifest_json: {ex}", 0, None
    if not isinstance(doc, dict):
        return "manifest_verification_failed: manifest_not_object", 0, None
    ver = doc.get("schema_version")
    if ver != 1:
        return f"manifest_verification_failed: unsupported_schema_version:{ver!r}", 0, None
    files = doc.get("files")
    if not isinstance(files, list):
        return "manifest_verification_failed: files_not_list", 0, None
    ext_res = ext_root.resolve()
    verified = 0
    for ent in files:
        if not isinstance(ent, dict):
            return "manifest_verification_failed: file_entry_not_object", verified, 1
        rel = str(ent.get("path") or "").replace("\\", "/").strip("/")
        if not rel or not _safe_member_name(rel):
            return f"manifest_verification_failed: unsafe_path:{rel[:120]!r}", verified, 1
        exp_size = ent.get("size")
        exp_hash = str(ent.get("sha256") or "").strip().lower()
        try:
            exp_sz_i = int(exp_size) if exp_size is not None else -1
        except (TypeError, ValueError):
            return "manifest_verification_failed: invalid_size", verified, 1
        if exp_sz_i < 0 or len(exp_hash) != 64 or any(c not in "0123456789abcdef" for c in exp_hash):
            return "manifest_verification_failed: invalid_digest_or_size", verified, 1
        target = (ext_root / rel).resolve()
        try:
            target.relative_to(ext_res)
        except ValueError:
            return f"manifest_verification_failed: path_escape:{rel[:120]!r}", verified, 1
        if not target.is_file():
            return f"manifest_verification_failed: missing_file:{rel[:200]!r}", verified, 1
        act_sz = int(target.stat().st_size)
        if act_sz != exp_sz_i:
            return f"manifest_verification_failed: size_mismatch:{rel[:160]!r}", verified, 1
        h = hashlib.sha256()
        with open(target, "rb") as f:
            while True:
                chunk = f.read(256 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        if h.hexdigest() != exp_hash:
            return f"manifest_verification_failed: sha256_mismatch:{rel[:160]!r}", verified, 1
        verified += 1
    return None, verified, 1


def extract_archive_simple(
    data: bytes,
    *,
    data_dir: Path,
    job_id: str,
    profile: dict[str, Any],
    manifest_required: bool = False,
) -> tuple[int, str, str | None, int, int | None]:
    """
    Extract tarball (optional gzip wrap) to ``job-workspaces/{id}/extracted/``.
    Returns ``(uncompressed_sum_bytes, sha256_hex_of_upload, error_or_none,
    manifest_files_verified, manifest_schema_version)``.
    """
    max_unc = int(profile.get("max_uncompressed_bytes") or 200 * 1024 * 1024)
    max_files = int(profile.get("max_files") or 50_000)
    max_depth = int(profile.get("max_path_depth") or 40)

    jdir = job_workspace_dir(data_dir, job_id)
    if jdir.exists():
        shutil.rmtree(jdir, ignore_errors=True)
    ext_root = jdir / "extracted"
    jdir.mkdir(parents=True, exist_ok=True)
    (jdir / "upload.raw").write_bytes(data)
    sha_body = hashlib.sha256(data).hexdigest()

    is_gz = len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B
    try:
        mode = "r:gz" if is_gz else "r:"
        tf = tarfile.open(fileobj=io.BytesIO(data), mode=mode)
    except (tarfile.TarError, OSError, EOFError) as ex:
        shutil.rmtree(jdir, ignore_errors=True)
        return 0, sha_body, f"invalid_archive: {ex}", 0, None

    unc_bytes = 0
    n_files = 0
    try:
        members = tf.getmembers()
        for m in members:
            name = m.name.replace("\\", "/").strip("/")
            if not name:
                continue
            if not _safe_member_name(name):
                tf.close()
                shutil.rmtree(jdir, ignore_errors=True)
                return 0, sha_body, "unsafe_path_in_archive", 0, None
            depth = len(Path(name).parts)
            if depth > max_depth:
                tf.close()
                shutil.rmtree(jdir, ignore_errors=True)
                return 0, sha_body, "path_too_deep", 0, None
            if m.issym() or m.islnk():
                tf.close()
                shutil.rmtree(jdir, ignore_errors=True)
                return 0, sha_body, "symlink_not_allowed", 0, None
            if m.isfile():
                sz = int(getattr(m, "size", 0) or 0)
                unc_bytes += sz
                if unc_bytes > max_unc:
                    tf.close()
                    shutil.rmtree(jdir, ignore_errors=True)
                    return 0, sha_body, "uncompressed_size_exceeded", 0, None
                n_files += 1
                if n_files > max_files:
                    tf.close()
                    shutil.rmtree(jdir, ignore_errors=True)
                    return 0, sha_body, "too_many_files", 0, None

        ext_root.mkdir(parents=True, exist_ok=True)
        if sys.version_info >= (3, 12):
            tf.extractall(ext_root, filter="data")
        else:
            members_sorted = sorted(
                members,
                key=lambda m: (len(Path(m.name.replace("\\", "/").strip("/")).parts), m.name),
            )
            for m in members_sorted:
                try:
                    _extract_member_safe(tf, m, ext_root)
                except OSError:
                    tf.close()
                    shutil.rmtree(jdir, ignore_errors=True)
                    return 0, sha_body, "extract_failed", 0, None
    except (tarfile.TarError, OSError) as ex:
        tf.close()
        shutil.rmtree(jdir, ignore_errors=True)
        return 0, sha_body, f"extract_failed: {ex}", 0, None
    finally:
        try:
            tf.close()
        except OSError:
            pass

    m_err, m_ver, m_schema = verify_extracted_workspace_manifest(ext_root, manifest_required=manifest_required)
    if m_err:
        shutil.rmtree(jdir, ignore_errors=True)
        return 0, sha_body, m_err, 0, None
    return unc_bytes, sha_body, None, m_ver, m_schema


def cleanup_job_workspace(data_dir: Path, job_id: str) -> None:
    jdir = job_workspace_dir(data_dir, job_id)
    if jdir.is_dir():
        shutil.rmtree(jdir, ignore_errors=True)


def gc_stale_workspaces(data_dir: Path, db_path: Path, *, max_age_seconds: float = 86400.0) -> int:
    """Remove stale per-job workspace dirs (orphan or terminal jobs older than max_age)."""
    from fleet_server import store

    root = data_dir / "job-workspaces"
    if not root.is_dir():
        return 0
    removed = 0
    now = time.time()
    conn = store.connect(db_path)
    try:
        for child in root.iterdir():
            if not child.is_dir():
                continue
            jid = child.name
            if not re.match(r"^[0-9a-f]{32}$", jid):
                continue
            row = store.get_job(conn, jid)
            stale = False
            if row is None:
                stale = True
            else:
                st = str(row.get("status") or "").lower()
                if st in ("completed", "failed", "cancelled"):
                    updated = float(row.get("updated") or 0)
                    if now - updated > max_age_seconds:
                        stale = True
                elif st == "queued":
                    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
                    if meta.get("workspace_upload_required") and meta.get("workspace_state") == "pending_upload":
                        created = float(row.get("created") or row.get("updated") or 0)
                        if created and now - created > max_age_seconds:
                            stale = True
            if stale:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
    finally:
        conn.close()
    return removed


def inject_workspace_bind_mount(
    argv: list[str],
    *,
    host_extracted: Path,
    container_mount: str,
) -> list[str]:
    """Insert ``-v host:container:ro`` immediately after ``docker … run``."""
    if len(argv) < 2:
        return argv
    try:
        run_idx = argv.index("run")
    except ValueError:
        return argv
    pair = ["-v", f"{host_extracted}:{container_mount.rstrip('/')}:ro"]
    ins = run_idx + 1
    return argv[:ins] + pair + argv[ins:]


def extract_tarball_bytes_to_directory(
    data: bytes,
    dest_root: Path,
    *,
    max_uncompressed_bytes: int,
    max_files: int,
    max_path_depth: int,
) -> str | None:
    """
    Safely extract a gzip tarball (or uncompressed tar) into ``dest_root``.

    Returns ``None`` on success, or a short machine-readable error token on failure.
    """
    is_gz = len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B
    try:
        mode = "r:gz" if is_gz else "r:"
        tf = tarfile.open(fileobj=io.BytesIO(data), mode=mode)
    except (tarfile.TarError, OSError, EOFError) as ex:
        return f"invalid_archive:{ex}"

    unc_bytes = 0
    n_files = 0
    try:
        members = tf.getmembers()
        for m in members:
            name = m.name.replace("\\", "/").strip("/")
            if not name:
                continue
            if not _safe_member_name(name):
                return "unsafe_path_in_archive"
            depth = len(Path(name).parts)
            if depth > max_path_depth:
                return "path_too_deep"
            if m.issym() or m.islnk():
                return "symlink_not_allowed"
            if m.isfile():
                sz = int(getattr(m, "size", 0) or 0)
                unc_bytes += sz
                if unc_bytes > max_uncompressed_bytes:
                    return "uncompressed_size_exceeded"
                n_files += 1
                if n_files > max_files:
                    return "too_many_files"

        dest_root.mkdir(parents=True, exist_ok=True)
        if sys.version_info >= (3, 12):
            tf.extractall(dest_root, filter="data")
        else:
            members_sorted = sorted(
                members,
                key=lambda m2: (len(Path(m2.name.replace("\\", "/").strip("/")).parts), m2.name),
            )
            for m in members_sorted:
                try:
                    _extract_member_safe(tf, m, dest_root)
                except OSError:
                    return "extract_failed"
    except (tarfile.TarError, OSError) as ex:
        return f"extract_failed:{ex}"
    finally:
        try:
            tf.close()
        except OSError:
            pass
    return None
