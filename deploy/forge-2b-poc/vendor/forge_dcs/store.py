"""Immutable, single-principal source registry (P02).

Layout under ``DCS_STORE_ROOT`` (absolute path, outside the source tree; fail closed if unset):

    <root>/STORE_FORMAT                      "dcs-store-v0.2" (v0.1 opened and upgraded additively)
    <root>/tenants/<tenant_key>/meta.sqlite3 metadata (WAL off, synchronous=FULL)
    <root>/tenants/<tenant_key>/blobs/<hh>/<sha256-hex>   content-addressed original bytes

``tenant_key`` is ``sha256(tenant_id)[:32]`` — every tenant has its own directory *and* its
own SQLite file, and every query is additionally keyed by ``tenant_id``; nothing can be read
across tenants by construction. The service is single-principal today; the namespace exists
so that the data layout does not have to change when a second principal arrives.

Write protocol (crash-safe, idempotent):

1. validate (id, MIME, size, UTF-8, JSON) — nothing is written on failure;
2. blob: write to ``blobs/.tmp-<random>`` with ``O_EXCL``, ``fsync``, ``os.replace`` onto the
   content-addressed path (a concurrent identical write lands on the same path, bytes equal);
3. metadata: ``BEGIN IMMEDIATE`` (writer lock) → if ``(tenant, file_id, content_hash)`` exists
   return it (idempotent, no new version) → else ``version = max+1`` → insert source row and
   its complete fragment inventory → ``COMMIT``.

A crash between 2 and 3 leaves an orphan blob (harmless, content-addressed); a crash inside 3
rolls back. No row can exist without its blob. There are no update or delete operations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from forge_dcs import errors
from forge_dcs.canonical import NORMALIZATION_VERSION, digest, normalize_prompt
from forge_dcs.contracts import FILE_ID_PATTERN
from forge_dcs.fragments import PARSER_ID, Fragment, inventory

ENV_STORE_ROOT = "DCS_STORE_ROOT"
STORE_FORMAT = "dcs-store-v0.2"
#: Older markers this code can open. v0.1 → v0.2 is additive (one nullable column); the marker is
#: rewritten on first open and v0.1 rows get their provenance synthesized from the fixed columns.
READABLE_FORMATS = ("dcs-store-v0.1", STORE_FORMAT)
PROVENANCE_VERSION = "dcs.provenance.v0.1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024
ACCEPTED_MIME = ("text/plain", "text/markdown", "application/json")
_FILE_ID = re.compile(FILE_ID_PATTERN)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  tenant_id TEXT NOT NULL, file_id TEXT NOT NULL, version TEXT NOT NULL, ordinal INTEGER NOT NULL,
  content_hash TEXT NOT NULL, mime TEXT NOT NULL, byte_length INTEGER NOT NULL,
  parser_id TEXT NOT NULL, created_utc TEXT NOT NULL, provenance_json TEXT,
  PRIMARY KEY (tenant_id, file_id, version),
  UNIQUE (tenant_id, file_id, ordinal),
  UNIQUE (tenant_id, file_id, content_hash)
);
CREATE TABLE IF NOT EXISTS fragments (
  tenant_id TEXT NOT NULL, file_id TEXT NOT NULL, version TEXT NOT NULL, fragment_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL, byte_start INTEGER NOT NULL, byte_end INTEGER NOT NULL, sha256 TEXT NOT NULL,
  PRIMARY KEY (tenant_id, file_id, version, fragment_id),
  FOREIGN KEY (tenant_id, file_id, version) REFERENCES sources (tenant_id, file_id, version)
);
CREATE TABLE IF NOT EXISTS prompts (
  tenant_id TEXT NOT NULL, prompt_sha256 TEXT NOT NULL, byte_length INTEGER NOT NULL,
  normalized_prompt_digest TEXT NOT NULL, normalization_version TEXT NOT NULL, created_utc TEXT NOT NULL,
  PRIMARY KEY (tenant_id, prompt_sha256)
);
"""


@dataclass(frozen=True)
class SourceRecord:
    tenant_id: str
    file_id: str
    version: str
    content_hash: str
    mime: str
    byte_length: int
    parser_id: str
    created_utc: str
    fragment_count: int
    #: Extensible provenance object (``PROVENANCE_VERSION``). Fixed columns above are the indexed
    #: facts; this object is the carrier for later phases (P04: ``tokenizer_source``) so the row
    #: layout does not change again. Stored as canonical JSON; never mutated after ingest.
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_provenance(mime: str, byte_length: int, parser_id: str) -> dict[str, Any]:
    """The provenance object written at ingest. Keys are stable; new keys may be added in later
    versions, existing keys are never removed or re-typed. ``tokenizer_source`` is reserved for P04
    and is ``None`` until a tokenizer fact source exists (none in the Granite catalog, EB1)."""
    return {
        "provenance_version": PROVENANCE_VERSION,
        "mime": mime,
        "byte_length": byte_length,
        "fragment_parser_id": parser_id,
        "tokenizer_source": None,
    }


def _provenance_json(p: dict[str, Any]) -> str:
    return json.dumps(p, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class PromptRecord:
    tenant_id: str
    prompt_sha256: str
    byte_length: int
    normalized_prompt_digest: str
    normalization_version: str
    created_utc: str
    handle: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoreConfig:
    root: Path | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "StoreConfig":
        e = env if env is not None else os.environ
        raw = (e.get(ENV_STORE_ROOT) or "").strip()
        return cls(root=Path(raw) if raw else None)

    def open(self) -> "SourceStore":
        if self.root is None or not self.root.is_absolute():
            raise errors.DcsError(
                errors.STORE_NOT_CONFIGURED, f"{ENV_STORE_ROOT} must be an absolute path to the source store", http_status=503
            )
        return SourceStore(self.root)


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_blob_nofollow(path: Path) -> bytes:
    """Open a blob without following symlinks; a symlinked blob means the store was tampered with."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError as exc:  # ELOOP for symlinks, ENOENT for missing blobs
        raise errors.DcsError(
            errors.SOURCE_CONTENT_INVALID, f"blob unreadable or not a regular file ({exc.__class__.__name__})", http_status=500
        ) from exc
    with os.fdopen(fd, "rb") as fh:
        if not os.path.isfile(path) or os.fstat(fd).st_nlink < 1:
            raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "blob is not a regular file", http_status=500)
        return fh.read(MAX_SOURCE_BYTES + 1)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_source(file_id: str, mime: str, data: bytes) -> None:
    """All P02 ingestion preconditions; raises typed DcsError, writes nothing."""
    if not isinstance(file_id, str) or not _FILE_ID.match(file_id) or ".." in file_id:
        raise errors.DcsError(errors.SOURCE_ID_INVALID, "file_id must match the identifier grammar", http_status=422)
    if mime not in ACCEPTED_MIME:
        raise errors.DcsError(errors.SOURCE_MIME_UNSUPPORTED, f"mime {mime!r} not in {list(ACCEPTED_MIME)}", http_status=415)
    if len(data) > MAX_SOURCE_BYTES:
        raise errors.DcsError(errors.SOURCE_TOO_LARGE, f"source exceeds {MAX_SOURCE_BYTES} bytes", http_status=413)
    if len(data) == 0:
        raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "empty source", http_status=422)
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise errors.DcsError(errors.SOURCE_ENCODING_INVALID, "source is not valid UTF-8", http_status=422) from exc
    if "\x00" in text:
        raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "NUL bytes are not permitted in text sources", http_status=422)
    if mime == "application/json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, f"invalid JSON: {exc.msg} at {exc.pos}", http_status=422) from exc


class SourceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / "STORE_FORMAT"
        if marker.exists():
            found = marker.read_text(encoding="utf-8").strip()
            if found not in READABLE_FORMATS:
                raise errors.DcsError(errors.STORE_NOT_CONFIGURED, f"store format {found!r} not in {READABLE_FORMATS!r}", http_status=503)
            if found != STORE_FORMAT:
                self.upgraded_from = found
                marker.write_text(STORE_FORMAT + "\n", encoding="utf-8")
            else:
                self.upgraded_from = None
        else:
            self.upgraded_from = None
            marker.write_text(STORE_FORMAT + "\n", encoding="utf-8")

    # --- tenant namespace -------------------------------------------------------------------

    @staticmethod
    def tenant_key(tenant_id: str) -> str:
        return _sha256_hex(tenant_id.encode("utf-8"))[:32]

    def _tenant_dir(self, tenant_id: str) -> Path:
        d = self.root / "tenants" / self.tenant_key(tenant_id)
        (d / "blobs").mkdir(parents=True, exist_ok=True)
        return d

    def _db(self, tenant_id: str) -> sqlite3.Connection:
        conn = sqlite3.connect(self._tenant_dir(tenant_id) / "meta.sqlite3", isolation_level=None, timeout=10.0)
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        # v0.1 → v0.2: additive, idempotent. Existing rows keep NULL and are synthesized on read.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sources)").fetchall()}
        if "provenance_json" not in cols:
            conn.execute("ALTER TABLE sources ADD COLUMN provenance_json TEXT")
        return conn

    def _blob_path(self, tenant_id: str, sha_hex: str) -> Path:
        return self._tenant_dir(tenant_id) / "blobs" / sha_hex[:2] / sha_hex

    # --- blobs --------------------------------------------------------------------------------

    def _write_blob(self, tenant_id: str, data: bytes) -> str:
        sha_hex = _sha256_hex(data)
        final = self._blob_path(tenant_id, sha_hex)
        if final.is_symlink():
            raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "blob path is a symlink; store refused", http_status=500)
        if final.exists():
            if final.stat().st_size != len(data):  # pragma: no cover - would mean a corrupted store
                raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "existing blob size mismatch", http_status=500)
            return sha_hex
        final.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=final.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
        os.chmod(final, 0o440)
        return sha_hex

    def read_bytes(self, tenant_id: str, file_id: str, version: str) -> bytes:
        """Bounded, tenant-scoped read of the original bytes; verifies the content hash."""
        rec = self.get_version(tenant_id, file_id, version)
        if rec is None:
            raise errors.DcsError(errors.SOURCE_NOT_FOUND, f"{file_id}@{version} not registered", http_status=404)
        data = _read_blob_nofollow(self._blob_path(tenant_id, rec.content_hash.split(":", 1)[1]))
        if "sha256:" + _sha256_hex(data) != rec.content_hash:  # pragma: no cover - corrupted store
            raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "stored bytes do not match content_hash", http_status=500)
        return data

    def read_fragment(self, tenant_id: str, file_id: str, version: str, fragment_id: str) -> bytes:
        data = self.read_bytes(tenant_id, file_id, version)
        for f in self.list_fragments(tenant_id, file_id, version):
            if f.fragment_id == fragment_id:
                chunk = data[f.byte_start : f.byte_end]
                if "sha256:" + _sha256_hex(chunk) != f.sha256:  # pragma: no cover - corrupted store
                    raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "fragment bytes do not match digest", http_status=500)
                return chunk
        raise errors.DcsError(errors.SOURCE_NOT_FOUND, f"fragment {fragment_id!r} not registered for {file_id}@{version}", http_status=404)

    # --- ingest -------------------------------------------------------------------------------

    def ingest(self, tenant_id: str, file_id: str, mime: str, data: bytes) -> tuple[SourceRecord, bool]:
        """Returns ``(record, created)``; ``created`` is False when idempotent."""
        validate_source(file_id, mime, data)
        content_hash = "sha256:" + self._write_blob(tenant_id, data)
        frags = inventory(data, mime)
        conn = self._db(tenant_id)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT version FROM sources WHERE tenant_id=? AND file_id=? AND content_hash=?", (tenant_id, file_id, content_hash)
            ).fetchone()
            if row:
                conn.execute("COMMIT")
                rec = self.get_version(tenant_id, file_id, row[0])
                assert rec is not None
                return rec, False
            ordinal = (conn.execute("SELECT COALESCE(MAX(ordinal),0) FROM sources WHERE tenant_id=? AND file_id=?", (tenant_id, file_id)).fetchone()[0]) + 1
            version = f"v{ordinal}"
            created = _now_utc()
            prov = make_provenance(mime, len(data), PARSER_ID)
            conn.execute(
                "INSERT INTO sources (tenant_id, file_id, version, ordinal, content_hash, mime, byte_length, parser_id, created_utc, provenance_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tenant_id, file_id, version, ordinal, content_hash, mime, len(data), PARSER_ID, created, _provenance_json(prov)),
            )
            conn.executemany(
                "INSERT INTO fragments VALUES (?,?,?,?,?,?,?,?)",
                [(tenant_id, file_id, version, f.fragment_id, f.ordinal, f.byte_start, f.byte_end, f.sha256) for f in frags],
            )
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        return SourceRecord(tenant_id, file_id, version, content_hash, mime, len(data), PARSER_ID, created, len(frags), prov), True

    # --- read ---------------------------------------------------------------------------------

    def get_version(self, tenant_id: str, file_id: str, version: str) -> SourceRecord | None:
        conn = self._db(tenant_id)
        try:
            row = conn.execute(
                "SELECT content_hash, mime, byte_length, parser_id, created_utc, "
                "(SELECT COUNT(*) FROM fragments f WHERE f.tenant_id=s.tenant_id AND f.file_id=s.file_id AND f.version=s.version), "
                "provenance_json FROM sources s WHERE tenant_id=? AND file_id=? AND version=?",
                (tenant_id, file_id, version),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        # v0.1 rows have no stored object: synthesize from the fixed columns (same shape, same values)
        prov = json.loads(row[6]) if row[6] else make_provenance(row[1], row[2], row[3])
        return SourceRecord(tenant_id, file_id, version, row[0], row[1], row[2], row[3], row[4], row[5], prov)

    def list_versions(self, tenant_id: str, file_id: str) -> list[SourceRecord]:
        conn = self._db(tenant_id)
        try:
            rows = conn.execute("SELECT version FROM sources WHERE tenant_id=? AND file_id=? ORDER BY ordinal", (tenant_id, file_id)).fetchall()
        finally:
            conn.close()
        return [r for r in (self.get_version(tenant_id, file_id, v[0]) for v in rows) if r is not None]

    def list_fragments(self, tenant_id: str, file_id: str, version: str) -> list[Fragment]:
        conn = self._db(tenant_id)
        try:
            rows = conn.execute(
                "SELECT fragment_id, ordinal, byte_start, byte_end, sha256 FROM fragments WHERE tenant_id=? AND file_id=? AND version=? ORDER BY ordinal",
                (tenant_id, file_id, version),
            ).fetchall()
        finally:
            conn.close()
        return [Fragment(*r) for r in rows]

    # --- compile-time authorization -----------------------------------------------------------

    def resolve(self, tenant_id: str, refs: Iterable[Any]) -> list[dict[str, Any]]:
        """Each ref needs ``file_id``, ``version``, ``content_hash``. Returns problems (empty = all
        registered **and** the persisted bytes re-hash to the claimed content hash)."""
        problems: list[dict[str, Any]] = []
        for r in refs:
            rec = self.get_version(tenant_id, r.file_id, r.version)
            if rec is None or rec.content_hash != r.content_hash:
                problems.append({"code": errors.SOURCE_VERSION_UNKNOWN, "file_id": r.file_id, "version": r.version, "message": "not registered for this tenant with this content_hash"})
                continue
            try:
                self.read_bytes(tenant_id, r.file_id, r.version)
            except errors.DcsError as exc:
                problems.append({"code": exc.code, "file_id": r.file_id, "version": r.version, "message": exc.message})
        return problems

    def fragment_index(self, tenant_id: str, refs: Iterable[Any]) -> dict[tuple[str, str], set[str]]:
        return {(r.file_id, r.version): {f.fragment_id for f in self.list_fragments(tenant_id, r.file_id, r.version)} for r in refs}

    # --- raw prompt custody (contract: prompt_artifact.v0.1) -----------------------------------

    def register_prompt(self, tenant_id: str, prompt: str) -> tuple[PromptRecord, bool]:
        """Stores the **raw** UTF-8 bytes of the prompt (no normalization) under the tenant,
        content-addressed by ``prompt_sha256``; records the normalized digest alongside so the
        two identities are linked but never conflated (F3)."""
        raw = prompt.encode("utf-8")
        if not raw or len(raw) > MAX_SOURCE_BYTES:
            raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "prompt must be 1..MAX_SOURCE_BYTES bytes", http_status=422)
        sha_hex = self._write_blob(tenant_id, raw)
        prompt_sha256 = "sha256:" + sha_hex
        conn = self._db(tenant_id)
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT created_utc, normalized_prompt_digest FROM prompts WHERE tenant_id=? AND prompt_sha256=?", (tenant_id, prompt_sha256)).fetchone()
            if row:
                conn.execute("COMMIT")
                return PromptRecord(tenant_id, prompt_sha256, len(raw), row[1], NORMALIZATION_VERSION, row[0], f"prompt:{sha_hex}"), False
            created = _now_utc()
            ndig = digest(normalize_prompt(prompt))
            conn.execute("INSERT INTO prompts VALUES (?,?,?,?,?,?)", (tenant_id, prompt_sha256, len(raw), ndig, NORMALIZATION_VERSION, created))
            conn.execute("COMMIT")
        except BaseException:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()
        return PromptRecord(tenant_id, prompt_sha256, len(raw), ndig, NORMALIZATION_VERSION, created, f"prompt:{sha_hex}"), True

    def read_prompt(self, tenant_id: str, prompt_sha256: str) -> bytes:
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", prompt_sha256):
            raise errors.DcsError(errors.SOURCE_NOT_FOUND, "prompt handle malformed", http_status=404)
        conn = self._db(tenant_id)
        try:
            row = conn.execute("SELECT 1 FROM prompts WHERE tenant_id=? AND prompt_sha256=?", (tenant_id, prompt_sha256)).fetchone()
        finally:
            conn.close()
        if not row:
            raise errors.DcsError(errors.SOURCE_NOT_FOUND, "prompt not registered for this tenant", http_status=404)
        data = self._blob_path(tenant_id, prompt_sha256.split(":", 1)[1]).read_bytes()
        if "sha256:" + _sha256_hex(data) != prompt_sha256:  # pragma: no cover - corrupted store
            raise errors.DcsError(errors.SOURCE_CONTENT_INVALID, "stored prompt bytes do not match digest", http_status=500)
        return data
