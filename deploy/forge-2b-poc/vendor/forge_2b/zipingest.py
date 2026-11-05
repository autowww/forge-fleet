"""Deterministic, bounded ZIP ingestion for Open WebUI attachments (P03).

Everything inside an archive is untrusted data. Nothing is executed, nothing is written to disk;
extraction happens in memory under hard limits, and the result is a manifest plus text blocks whose
integrity can be re-verified from the manifest hashes.
"""
from __future__ import annotations

import hashlib
import io
import json
import mimetypes
import posixpath
import re
import unicodedata
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any

MANIFEST_VERSION = "forge-zip.v1"
TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".py", ".js", ".ts", ".toml", ".xml", ".html", ".htm",
    ".sql", ".log", ".sh", ".ini", ".cfg", ".rst", ".tsv", ".env.example",
}
TEXT_BASENAMES = {"README", "LICENSE", "NOTICE", "Dockerfile", "Makefile", ".gitignore", ".dockerignore", "CHANGELOG"}
ARCHIVE_EXTENSIONS = {".zip", ".jar", ".war", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst"}
TEXT_MIME = {".md": "text/markdown", ".txt": "text/plain", ".json": "application/json", ".yaml": "application/yaml",
             ".yml": "application/yaml", ".csv": "text/csv", ".py": "text/x-python", ".js": "text/javascript",
             ".ts": "text/typescript", ".toml": "application/toml", ".xml": "application/xml", ".html": "text/html",
             ".htm": "text/html", ".sql": "application/sql", ".log": "text/plain", ".sh": "text/x-shellscript"}

_MARK_BEGIN = "===== FORGE-ZIP MANIFEST {nonce} ====="
_MARK_END = "===== END FORGE-ZIP MANIFEST {nonce} ====="
_FILE_BEGIN = "----- forge-zip {nonce} file: {path} -----"
_FILE_END = "----- forge-zip {nonce} end: {path} -----"
_BEGIN_RE = re.compile(r"===== FORGE-ZIP MANIFEST ([0-9a-f]{12}) =====")  # may follow a <source> tag on the same line


class ZipIngestError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Limits:
    max_archive_bytes: int = 64 * 1024 * 1024
    max_total_uncompressed: int = 128 * 1024 * 1024
    max_file_bytes: int = 8 * 1024 * 1024
    max_files: int = 500
    max_path_len: int = 240
    max_ratio: int = 100  # per-entry decompression ratio guard (bomb)
    ratio_floor_bytes: int = 1024 * 1024  # ratio only enforced above this uncompressed size


@dataclass
class Entry:
    path: str
    normalized_name: str
    mime: str
    bytes: int
    sha256: str  # hash of the extracted bytes ("" when not extracted)
    status: str  # INCLUDED | SKIPPED
    skip_reason: str = ""
    lines: int = 0
    content_sha256: str = ""  # hash of the rendered text (what the model may see)
    rendered: str = ""  # "" | "text" | "html_text" | "latin1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Ingest:
    archive_id: str  # sha256:<hex> of the archive bytes
    filename: str
    manifest_version: str = MANIFEST_VERSION
    entries: list[Entry] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)  # path -> rendered text (INCLUDED only)
    truncated: bool = False  # file count cap reached
    integrity: dict[str, str] = field(default_factory=dict)  # path -> OK | MISSING | MISMATCH (set by parse)

    @property
    def nonce(self) -> str:
        return hashlib.sha256(f"forge-zip-marker:{self.archive_id}".encode()).hexdigest()[:12]

    @property
    def included(self) -> list[Entry]:
        return [e for e in self.entries if e.status == "INCLUDED"]

    @property
    def skipped(self) -> list[Entry]:
        return [e for e in self.entries if e.status == "SKIPPED"]

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "archive_id": self.archive_id,
            "filename": self.filename,
            "file_count": len(self.entries),
            "included": len(self.included),
            "skipped": len(self.skipped),
            "truncated": self.truncated,
            "entries": [e.to_dict() for e in self.entries],
        }


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def normalize_path(name: str) -> str | None:
    """Return a safe relative POSIX path or None (Zip Slip / absolute / drive / control chars)."""
    if not name or "\x00" in name or any(ord(c) < 32 for c in name):
        return None
    cand = name.replace("\\", "/")
    if cand.startswith("/") or re.match(r"^[A-Za-z]:", cand):
        return None
    cand = posixpath.normpath(cand)
    if cand in (".", "") or cand.startswith("../") or cand == ".." or "/../" in cand:
        return None
    return cand


def _ext(path: str) -> str:
    base = posixpath.basename(path)
    if base.lower().endswith(".env.example"):
        return ".env.example"
    return posixpath.splitext(base)[1].lower()


def _is_text_type(path: str) -> bool:
    base = posixpath.basename(path)
    return _ext(path) in TEXT_EXTENSIONS or base in TEXT_BASENAMES


def _mime_for(path: str) -> str:
    ext = _ext(path)
    if ext in TEXT_MIME:
        return TEXT_MIME[ext]
    guess, _ = mimetypes.guess_type(path)
    return guess or ("text/plain" if _is_text_type(path) else "application/octet-stream")


def decode_text(data: bytes) -> tuple[str, str] | None:
    """utf-8 (BOM tolerant) -> latin-1 fallback; None when it looks binary."""
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8-sig"), "text"
    except UnicodeDecodeError:
        pass
    sample = data[:4096]
    printable = sum(1 for b in sample if 32 <= b < 127 or b in (9, 10, 13) or b >= 160)
    if sample and printable / len(sample) < 0.9:
        return None
    return data.decode("latin-1"), "latin1"


def ingest_zip(data: bytes, filename: str, limits: Limits = Limits(), *, html_to_text=None) -> Ingest:
    """Extract an archive fully in memory under limits. Raises ZipIngestError only for whole-archive problems."""
    if len(data) > limits.max_archive_bytes:
        raise ZipIngestError("ZIP_TOO_LARGE", f"Archive exceeds {limits.max_archive_bytes} bytes")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ZipIngestError("ZIP_INVALID_SIGNATURE", "Not a ZIP archive (bad signature or truncated)")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, RuntimeError, ValueError, EOFError, OSError) as ex:
        raise ZipIngestError("ZIP_CORRUPT", f"Archive could not be read: {type(ex).__name__}") from ex
    # CRC is verified per entry while reading (bounded by limits) instead of testzip(), which would fully
    # decompress every entry including bombs and raise on encrypted members.

    ing = Ingest(archive_id=_sha(data), filename=posixpath.basename(filename.replace("\\", "/")) or "archive.zip")
    total = 0
    seen: set[str] = set()
    for info in sorted(infos, key=lambda i: i.filename):
        if info.is_dir():
            continue
        if len(ing.entries) >= limits.max_files:
            ing.truncated = True
            break
        raw_name = info.filename
        norm_name = unicodedata.normalize("NFC", raw_name)
        safe = normalize_path(norm_name)
        entry = Entry(path=safe or raw_name[:limits.max_path_len], normalized_name=norm_name, mime="", bytes=info.file_size,
                      sha256="", status="SKIPPED")
        if safe is None:
            entry.skip_reason = "unsafe_path"
            ing.entries.append(entry)
            continue
        if safe in seen:
            entry.skip_reason = "duplicate_path"
            ing.entries.append(entry)
            continue
        seen.add(safe)
        entry.mime = _mime_for(safe)
        if len(safe) > limits.max_path_len:
            entry.skip_reason = "path_too_long"
        elif info.flag_bits & 0x1:
            entry.skip_reason = "encrypted"
        elif _ext(safe) in ARCHIVE_EXTENSIONS:
            entry.skip_reason = "nested_archive"
        elif info.file_size > limits.max_file_bytes:
            entry.skip_reason = "file_too_large"
        elif info.file_size > limits.ratio_floor_bytes and info.file_size / max(1, info.compress_size) > limits.max_ratio:
            entry.skip_reason = "compression_ratio"
        elif total + info.file_size > limits.max_total_uncompressed:
            entry.skip_reason = "total_size_cap"
        elif not _is_text_type(safe):
            entry.skip_reason = "type_not_allowed"
        if entry.skip_reason:
            ing.entries.append(entry)
            continue
        try:
            with zf.open(info) as fh:
                blob = fh.read(limits.max_file_bytes + 1)
        except (zipfile.BadZipFile, zlib.error) as ex:  # CRC or stream damage: the archive is not trustworthy as a whole
            raise ZipIngestError("ZIP_CORRUPT", f"Damaged data in entry {safe!r}: {ex}") from ex
        except (RuntimeError, NotImplementedError, EOFError, OSError, ValueError) as ex:
            entry.skip_reason = f"read_error:{type(ex).__name__}"
            ing.entries.append(entry)
            continue
        if len(blob) > limits.max_file_bytes or len(blob) != info.file_size:
            entry.skip_reason = "size_mismatch"  # header lied (bomb pattern)
            ing.entries.append(entry)
            continue
        total += len(blob)
        entry.bytes = len(blob)
        entry.sha256 = _sha(blob)
        if blob[:4] == b"PK\x03\x04":
            entry.skip_reason = "nested_archive"
            ing.entries.append(entry)
            continue
        decoded = decode_text(blob)
        if decoded is None:
            entry.skip_reason = "binary_content"
            ing.entries.append(entry)
            continue
        text, how = decoded
        if _ext(safe) in (".html", ".htm") and html_to_text is not None:
            text = html_to_text(text)
            how = "html_text"
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        entry.status = "INCLUDED"
        entry.rendered = how
        entry.lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        entry.content_sha256 = _sha(text.encode("utf-8"))
        ing.files[safe] = text
        ing.entries.append(entry)
    return ing


def render(ing: Ingest) -> str:
    """Manifest (JSON) + file blocks, framed with archive-derived markers. Deterministic for the same archive."""
    n = ing.nonce
    out = [_MARK_BEGIN.format(nonce=n), json.dumps(ing.manifest_dict(), ensure_ascii=False, sort_keys=True, indent=1),
           _MARK_END.format(nonce=n)]
    for e in ing.included:
        out.append(_FILE_BEGIN.format(nonce=n, path=e.path))
        body = ing.files[e.path]
        out.append(body if body.endswith("\n") else body + "\n")
        out.append(_FILE_END.format(nonce=n, path=e.path))
    return "\n".join(out) + "\n"


def parse_rendered(text: str) -> list[Ingest]:
    """Rebuild Ingest objects from rendered text (as echoed back by Open WebUI); verifies block integrity."""
    results: list[Ingest] = []
    for m in _BEGIN_RE.finditer(text):
        nonce = m.group(1)
        end_mark = _MARK_END.format(nonce=nonce)
        end = text.find(end_mark, m.end())
        if end < 0:
            continue
        try:
            manifest = json.loads(text[m.end():end])
        except ValueError:
            continue
        if not isinstance(manifest, dict) or manifest.get("manifest_version") != MANIFEST_VERSION:
            continue
        ing = Ingest(archive_id=str(manifest.get("archive_id", "")), filename=str(manifest.get("filename", "")),
                     truncated=bool(manifest.get("truncated")))
        if ing.nonce != nonce:
            continue  # markers do not belong to this manifest
        for raw in manifest.get("entries", []):
            if not isinstance(raw, dict):
                continue
            try:
                ing.entries.append(Entry(**{k: raw.get(k, "") for k in Entry.__dataclass_fields__}))
            except TypeError:
                continue
        cursor = end + len(end_mark)
        for e in ing.included:
            fb = "\n" + _FILE_BEGIN.format(nonce=nonce, path=e.path) + "\n"
            fe = "\n" + _FILE_END.format(nonce=nonce, path=e.path)
            start = text.find(fb, cursor)
            if start < 0:
                ing.integrity[e.path] = "MISSING"
                continue
            stop = text.find(fe, start + len(fb))
            if stop < 0:
                ing.integrity[e.path] = "MISSING"
                continue
            body = text[start + len(fb):stop]
            candidates = [body] + ([body[:-1]] if body.endswith("\n") else [])  # render() adds one newline if missing
            match = next((c for c in candidates if _sha(c.encode("utf-8")) == e.content_sha256), None)
            if match is not None:
                ing.files[e.path] = match
                ing.integrity[e.path] = "OK"
            else:
                ing.integrity[e.path] = "MISMATCH"
            cursor = stop + len(fe)
        results.append(ing)
    return results


def render_manifest_markdown(ing: Ingest) -> str:
    rows = ["| # | path | status | bytes | lines | type | sha256 | note |", "|---|---|---|---|---|---|---|---|"]
    for i, e in enumerate(ing.entries, 1):
        note = e.skip_reason or ing.integrity.get(e.path, "")
        rows.append(f"| {i} | `{e.path}` | {e.status} | {e.bytes} | {e.lines or ''} | {e.mime} | `{e.sha256[7:19] if e.sha256 else '—'}` | {note} |")
    head = (f"**Archive** `{ing.filename}` · id `{ing.archive_id[:19]}…` · {len(ing.entries)} entries "
            f"({len(ing.included)} included, {len(ing.skipped)} skipped{', list truncated' if ing.truncated else ''})\n\n")
    return head + "\n".join(rows) + "\n"
