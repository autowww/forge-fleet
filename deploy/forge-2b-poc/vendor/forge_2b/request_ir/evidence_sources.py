"""DCE-G2 — attachment sources for the EvidenceGraph (schema ``forge.models.evidence_graph.v0.1``).

Turns caller-supplied attachments (uploads, pastes, tool outputs, ZIP archives) into **decoded, bounded, provenance-carrying
sources** plus structured *facts* (key/value lines, CSV cells, Markdown headings) with exact character offsets.

Everything here is data handling only:

* no network, no filesystem, no shell — bytes in, dataclasses out; the caller owns I/O;
* attachment content is **untrusted data** — nothing in it is ever read as an instruction, and this module never looks at a
  ``RequestIR``;
* every limit in :class:`ResourceLimits` is enforced and every skip is reported as a :class:`SourceWarning` — bounded partial
  evidence, never silent success;
* decoding never forges offsets: UTF-8 (strict, then BOM-aware) or an explicit ``latin-1`` fallback whose byte↔char mapping is
  1:1, with the chosen encoding recorded on the :class:`SourceRef`.

Pure standard library (``zipfile``, ``csv``, ``json``) — YAML and JSON facts come from a small positional scanner, not a full
parser, so that each fact carries the exact span it was read from.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import posixpath
import re
import stat
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

ORIGINS = ("upload", "paste", "tool_output")
MEDIA_TYPES = ("text", "markdown", "json", "yaml", "csv", "env", "zip", "binary", "unknown")
FACT_KINDS = ("key_value", "list_item", "cell", "heading")


# ------------------------------------------------------------------------------------------------------------- limits ---
@dataclass(frozen=True)
class ResourceLimits:
    """Hard caps. Defaults are deliberately small for a comprehension library; callers may raise them explicitly."""
    max_attachments: int = 32
    max_entry_bytes: int = 2 * 1024 * 1024          # per decoded source
    max_total_bytes: int = 16 * 1024 * 1024         # across all decoded sources
    max_zip_entries: int = 512
    max_compression_ratio: float = 100.0            # uncompressed / compressed per ZIP member
    allow_nested_archives: bool = False             # ZIP inside ZIP is listed and skipped unless enabled (one level only)
    max_facts_per_source: int = 5000
    max_lines_per_source: int = 50000
    max_csv_columns: int = 256

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# ------------------------------------------------------------------------------------------------------------- inputs ---
@dataclass(frozen=True)
class AttachmentInput:
    """What the caller hands in. Exactly one of ``content_bytes`` / ``text`` must be set."""
    name: str
    mime_type: Optional[str] = None
    content_bytes: Optional[bytes] = None
    text: Optional[str] = None
    origin: str = "upload"
    id: Optional[str] = None

    def __post_init__(self) -> None:
        if (self.content_bytes is None) == (self.text is None):
            raise TypeError("AttachmentInput needs exactly one of content_bytes or text")
        if self.origin not in ORIGINS:
            raise TypeError(f"origin must be one of {ORIGINS}")
        if not isinstance(self.name, str) or not self.name:
            raise TypeError("name must be a non-empty str")

    def raw(self) -> bytes:
        return self.content_bytes if self.content_bytes is not None else self.text.encode("utf-8", "surrogatepass")  # type: ignore[union-attr]


# ------------------------------------------------------------------------------------------------------------ outputs ---
@dataclass(frozen=True)
class SourceWarning:
    code: str            # see WARNING_CODES
    attachment: str      # attachment name (and member path for ZIP entries, joined by '!')
    detail: str


WARNING_CODES = (
    "too_many_attachments", "entry_too_large", "total_too_large", "binary_skipped", "decode_fallback_latin1",
    "zip_invalid", "zip_too_many_entries", "zip_unsafe_path", "zip_symlink", "zip_nested_archive", "zip_compression_ratio",
    "zip_duplicate_path", "zip_directory", "csv_malformed", "json_malformed", "facts_truncated", "lines_truncated",
    "unknown_media_type", "empty_source",
)


@dataclass(frozen=True)
class SourceRef:
    source_id: str                 # content-addressed: "s-" + sha256(origin|path|digest)[:16]
    attachment_digest: str         # "sha256:" of the raw bytes of this source (ZIP member bytes for members)
    normalized_safe_path: str      # posix, no leading '/', no '..'; "<zip name>!<member>" for ZIP members
    origin: str
    media_type: str                # MEDIA_TYPES
    encoding: Optional[str]        # "utf-8" | "utf-8-sig" | "latin-1" | None (binary / skipped)
    size_bytes: int
    decoded: bool                  # False → listed only (binary, too large, unsupported)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(slots=True)
class Fact:
    """A structured datum with its exact location. ``key`` is a dotted path for key/value data, a header name for CSV cells.
    (Not frozen: tens of thousands are created per large attachment and frozen ``__init__`` is measurably slower; treat as read-only.)"""
    source_id: str
    kind: str                      # FACT_KINDS
    key: Optional[str]
    value: Optional[str]           # raw scalar text as written (unquoted), None for headings
    char_start: int                # span of the *value* (or heading text / list item text)
    char_end: int
    line: int                      # 1-based line of char_start
    row: Optional[int] = None      # CSV: 1-based data row (header = 0)
    column: Optional[int] = None   # CSV: 0-based column
    key_start: Optional[int] = None
    key_end: Optional[int] = None


@dataclass
class DecodedSource:
    ref: SourceRef
    text: str                      # "" when not decoded
    line_starts: list[int] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)


@dataclass
class SourceSet:
    sources: list[DecodedSource]
    warnings: list[SourceWarning]
    stats: dict[str, int]


# -------------------------------------------------------------------------------------------------------- utilities ---
def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def line_starts(text: str) -> list[int]:
    starts = [0]
    i = text.find("\n")
    while i >= 0:
        starts.append(i + 1)
        i = text.find("\n", i + 1)
    return starts


def line_of(starts: list[int], offset: int) -> int:
    """1-based line number for a char offset (binary search)."""
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def byte_offsets(text: str, encoding: str, char_start: int, char_end: int) -> tuple[int, int]:
    """Exact byte offsets of a char span in the original decoded bytes (BOM accounted for)."""
    if encoding == "latin-1":
        return char_start, char_end
    bom = 3 if encoding == "utf-8-sig" else 0
    enc = "utf-8"
    return bom + len(text[:char_start].encode(enc, "surrogatepass")), bom + len(text[:char_end].encode(enc, "surrogatepass"))


_EXT_MEDIA = {
    ".md": "markdown", ".markdown": "markdown", ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".csv": "csv", ".tsv": "csv",
    ".env": "env", ".ini": "env", ".toml": "env", ".cfg": "env", ".conf": "env", ".properties": "env", ".zip": "zip",
    ".txt": "text", ".log": "text", ".py": "text", ".sh": "text", ".sql": "text", ".js": "text", ".ts": "text", ".xml": "text",
    ".html": "text", ".htm": "text", ".tf": "text", ".dockerfile": "text",
}
_MIME_MEDIA = {
    "text/markdown": "markdown", "application/json": "json", "text/json": "json", "application/x-yaml": "yaml",
    "application/yaml": "yaml", "text/yaml": "yaml", "text/x-yaml": "yaml", "text/csv": "csv", "text/tab-separated-values": "csv",
    "application/zip": "zip", "application/x-zip-compressed": "zip", "text/plain": "text",
}
_ARCHIVE_EXT = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war")


def media_type_for(name: str, mime: Optional[str]) -> str:
    low = name.lower()
    if low.endswith(".dockerfile") or posixpath.basename(low) in ("dockerfile", "makefile"):
        return "text"
    for ext, mt in _EXT_MEDIA.items():
        if low.endswith(ext):
            return mt
    if mime:
        m = mime.split(";")[0].strip().lower()
        if m in _MIME_MEDIA:
            return _MIME_MEDIA[m]
        if m.startswith("text/"):
            return "text"
    return "unknown"


def normalize_safe_path(name: str) -> Optional[str]:
    """Posix-normalise; return None when the path is unsafe (absolute, drive, '..', empty)."""
    p = name.replace("\\", "/")
    if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p) or p.startswith("//"):
        return None
    norm = posixpath.normpath(p)
    if norm in (".", "") or norm.startswith("../") or norm == ".." or "/../" in f"/{norm}/":
        return None
    return norm


_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"%PDF-", b"\x7fELF", b"\x1f\x8b", b"BM", b"\x00\x00\x01\x00",
          b"RIFF", b"OggS", b"\x1a\x45\xdf\xa3", b"SQLite format 3\x00", b"PK\x03\x04", b"Rar!\x1a\x07", b"7z\xbc\xaf\x27\x1c", b"\xfd7zXZ\x00",
          b"BZh", b"\xca\xfe\xba\xbe", b"MZ")
_TEXT_CTRL_OK = frozenset(b"\t\n\r\f\v\x1b")


def _looks_binary(b: bytes) -> bool:
    """NUL byte, a known binary magic number, or more than 10 % control bytes in the head (G2 burned repair: PNG/JPEG/… headers
    shorter than 8 KB used to fall through to the latin-1 decoder)."""
    head = b[:8192]
    if not head:
        return False
    if b"\x00" in head or head.startswith(_MAGIC):
        return True
    ctrl = sum(1 for x in head if x < 32 and x not in _TEXT_CTRL_OK)
    return ctrl * 10 > len(head)


def decode_bytes(b: bytes) -> tuple[str, str]:
    """Return (text, encoding). UTF-8 strict first, then BOM-aware, then an explicit latin-1 fallback (1:1 byte↔char)."""
    if b.startswith(b"\xef\xbb\xbf"):
        try:
            return b[3:].decode("utf-8"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    try:
        return b.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return b.decode("latin-1"), "latin-1"


def _source_id(origin: str, path: str, digest: str) -> str:
    return "s-" + sha256_hex(f"{origin}|{path}|{digest}".encode("utf-8"))[:16]


# --------------------------------------------------------------------------------------------------- fact scanners ---
_YAML_KV = re.compile(r"^(?P<indent>[ \t]*)(?P<key>[A-Za-z0-9_.\-/\"']+?)\s*:(?:\s+(?P<val>.*?)\s*)?$")
_YAML_LIST = re.compile(r"^(?P<indent>[ \t]*)-\s+(?P<val>.*?)\s*$")
_ENV_KV = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_.\-]*)\s*(?P<op>=|:)\s*(?P<val>.*?)\s*$")
_INI_SECTION = re.compile(r"^\s*\[(?P<sec>[^\]]+)\]\s*$")
_MD_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
_MD_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_INLINE_COMMENT = re.compile(r"\s+#")


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _strip_inline_comment(v: str) -> str:
    # YAML/.env: ' #' begins a comment outside quotes
    if "#" not in v or (v and v[0] in "\"'"):
        return v
    m = _INLINE_COMMENT.search(v)
    return v[: m.start()] if m else v


def _lines_with_offsets(text: str, starts: list[int], max_lines: int) -> Iterable[tuple[int, int, str]]:
    lines = text.split("\n")
    n = min(len(lines), max_lines, len(starts))
    for i in range(n):
        line = lines[i]
        if line.endswith("\r"):
            line = line[:-1]
        yield i + 1, starts[i], line


def scan_yaml(sid: str, text: str, starts: list[int], limits: ResourceLimits) -> list[Fact]:
    facts: list[Fact] = []
    stack: list[tuple[int, str]] = []      # (indent, key)
    list_counters: dict[str, int] = {}
    in_fence = False
    for ln, off, line in _lines_with_offsets(text, starts, limits.max_lines_per_source):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped or stripped[0] == "#" or stripped == "---":
            continue
        ml = _YAML_LIST.match(line)
        if ml:
            indent = len(ml.group("indent").expandtabs(2))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent = ".".join(k for _, k in stack).replace(".[", "[") or "<root>"
            idx = list_counters.get(parent, 0)
            list_counters[parent] = idx + 1
            raw = _strip_inline_comment(ml.group("val"))
            inner = _YAML_KV.match(raw)
            vs = off + ml.start("val")
            if inner and inner.group("val") is not None and inner.group("val") != "":
                # "- name: x" — key/value inside a list item
                k = f"{parent}[{idx}].{_unquote(inner.group('key'))}"
                v = _unquote(_strip_inline_comment(inner.group("val")))
                v_start = vs + inner.start("val")
                facts.append(Fact(sid, "key_value", k, v, v_start, v_start + len(inner.group("val").rstrip()), ln,
                                  key_start=vs + inner.start("key"), key_end=vs + inner.end("key")))
                stack.append((indent + 1, f"[{idx}]"))          # nested keys of this list item: parent[idx].key
            else:
                facts.append(Fact(sid, "list_item", f"{parent}[{idx}]", _unquote(raw), vs, vs + len(raw), ln))
            if len(facts) >= limits.max_facts_per_source:
                break
            continue
        m = _YAML_KV.match(line)
        if not m:
            continue
        indent = len(m.group("indent").expandtabs(2))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        key = _unquote(m.group("key"))
        path = ".".join([k for _, k in stack] + [key]).replace(".[", "[")
        val = m.group("val")
        if val is None or val == "" or val in ("|", ">", "|-", ">-"):
            stack.append((indent, key))
            continue
        raw = _strip_inline_comment(val)
        vs = off + m.start("val")
        facts.append(Fact(sid, "key_value", path, _unquote(raw), vs, vs + len(raw), ln,
                          key_start=off + m.start("key"), key_end=off + m.end("key")))
        stack.append((indent, key))
        if len(facts) >= limits.max_facts_per_source:
            break
    return facts


def scan_env(sid: str, text: str, starts: list[int], limits: ResourceLimits) -> list[Fact]:
    facts: list[Fact] = []
    section = ""
    for ln, off, line in _lines_with_offsets(text, starts, limits.max_lines_per_source):
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        ms = _INI_SECTION.match(line)
        if ms:
            section = ms.group("sec").strip()
            continue
        m = _ENV_KV.match(line)
        if not m:
            continue
        raw = _strip_inline_comment(m.group("val"))
        vs = off + m.start("val")
        key = f"{section}.{m.group('key')}" if section else m.group("key")
        facts.append(Fact(sid, "key_value", key, _unquote(raw), vs, vs + len(raw), ln,
                          key_start=off + m.start("key"), key_end=off + m.end("key")))
        if len(facts) >= limits.max_facts_per_source:
            break
    return facts


def scan_json(sid: str, text: str, starts: list[int], limits: ResourceLimits) -> tuple[list[Fact], Optional[str]]:
    """Positional JSON scanner: emits key_value facts with dotted/indexed paths and exact scalar spans.

    Validity is checked with ``json.loads`` first; a malformed document yields no facts and an error string.
    """
    try:
        json.loads(text)
    except ValueError as e:
        return [], f"{e.__class__.__name__}: {str(e)[:120]}"
    facts: list[Fact] = []
    n = len(text)
    i = 0
    stack: list[dict[str, Any]] = []          # {"type": "obj"|"arr", "key": str|None, "idx": int}
    pending_key: Optional[tuple[str, int, int]] = None

    def path_now() -> str:
        parts: list[str] = []
        for fr in stack:
            if fr["type"] == "obj":
                if fr["key"] is not None:
                    parts.append(fr["key"])
            else:
                parts.append(f"[{fr['idx']}]")
        return ".".join(parts).replace(".[", "[") or "<root>"

    def read_string(j: int) -> tuple[str, int]:
        # j at opening quote; returns (decoded, index after closing quote)
        k = j + 1
        buf: list[str] = []
        while k < n:
            c = text[k]
            if c == "\\":
                buf.append(text[k:k + 2]); k += 2; continue
            if c == '"':
                return json.loads(text[j:k + 1]), k + 1
            buf.append(c); k += 1
        return "".join(buf), n

    while i < n and len(facts) < limits.max_facts_per_source:
        c = text[i]
        if c.isspace() or c == ",":
            i += 1; continue
        if c == "{":
            stack.append({"type": "obj", "key": None, "idx": 0}); i += 1; continue
        if c == "[":
            stack.append({"type": "arr", "key": None, "idx": 0}); i += 1; continue
        if c in "}]":
            stack.pop(); i += 1
            if stack and stack[-1]["type"] == "arr":
                stack[-1]["idx"] += 1
            if stack and stack[-1]["type"] == "obj":
                stack[-1]["key"] = None
            continue
        if c == ":":
            i += 1; continue
        # scalar or key
        if c == '"':
            s, j = read_string(i)
            in_obj = bool(stack) and stack[-1]["type"] == "obj"
            if in_obj and stack[-1]["key"] is None:
                stack[-1]["key"] = s; pending_key = (s, i + 1, j - 1); i = j; continue
            key = path_now()
            facts.append(Fact(sid, "key_value", key, s, i + 1, j - 1, line_of(starts, i),
                              key_start=pending_key[1] if pending_key and in_obj else None,
                              key_end=pending_key[2] if pending_key and in_obj else None))
            pending_key = None
            if in_obj:
                stack[-1]["key"] = None
            elif stack:
                stack[-1]["idx"] += 1
            i = j; continue
        m = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null", text[i:])
        if not m:
            i += 1; continue
        j = i + m.end()
        in_obj = bool(stack) and stack[-1]["type"] == "obj"
        facts.append(Fact(sid, "key_value", path_now(), m.group(0), i, j, line_of(starts, i),
                          key_start=pending_key[1] if pending_key and in_obj else None,
                          key_end=pending_key[2] if pending_key and in_obj else None))
        pending_key = None
        if in_obj:
            stack[-1]["key"] = None
        elif stack:
            stack[-1]["idx"] += 1
        i = j
    return facts, None


_JSON_LINE_KV = re.compile(r"^\s*[{\[,]?\s*\"(?P<key>[^\"\n]{1,120})\"\s*:\s*(?P<val>\"[^\"\n]*\"|-?\d+(?:\.\d+)?|true|false|null|[^,\s{}\[\]]+)")


def scan_json_lines(sid: str, text: str, starts: list[int], limits: ResourceLimits) -> list[Fact]:
    """Line-level fallback for malformed JSON: flat ``"key": value`` facts with exact spans; no nesting paths are inferred."""
    facts: list[Fact] = []
    for ln, off, line in _lines_with_offsets(text, starts, limits.max_lines_per_source):
        m = _JSON_LINE_KV.match(line)
        if not m:
            continue
        raw = m.group("val")
        vs = off + m.start("val")
        if raw.startswith('"'):
            facts.append(Fact(sid, "key_value", m.group("key"), raw[1:-1], vs + 1, vs + len(raw) - 1, ln,
                              key_start=off + m.start("key"), key_end=off + m.end("key")))
        else:
            facts.append(Fact(sid, "key_value", m.group("key"), raw, vs, vs + len(raw), ln,
                              key_start=off + m.start("key"), key_end=off + m.end("key")))
        if len(facts) >= limits.max_facts_per_source:
            break
    return facts


def scan_csv(sid: str, text: str, starts: list[int], limits: ResourceLimits) -> tuple[list[Fact], Optional[str]]:
    facts: list[Fact] = []
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    header: list[str] = []
    err: Optional[str] = None
    delim = getattr(dialect, "delimiter", ",")
    quote = getattr(dialect, "quotechar", '"') or '"'
    for ln, off, line in _lines_with_offsets(text, starts, limits.max_lines_per_source):
        if not line.strip():
            continue
        if line.count(quote) % 2 == 1:
            # unbalanced quote on a line: the csv module silently swallows it in non-strict mode (G2 burned repair)
            err = err or f"line {ln}: unbalanced {quote!r}"
            continue
        if '"' not in line and "'" not in line:
            cells = line.split(delim)                 # unquoted line: identical to csv.reader, without the per-line reader
        else:
            try:
                cells = next(csv.reader([line], dialect))
            except csv.Error as e:
                err = err or f"line {ln}: {e}"
                continue
        if len(cells) > limits.max_csv_columns:
            err = err or f"line {ln}: {len(cells)} columns > {limits.max_csv_columns}"
            cells = cells[: limits.max_csv_columns]
        if not header:
            header = [c.strip() for c in cells]
            cursor = 0
            for col, cell in enumerate(cells):
                pos = line.find(cell, cursor) if cell else -1
                if pos >= 0:
                    facts.append(Fact(sid, "heading", header[col], None, off + pos, off + pos + len(cell), ln, row=0, column=col))
                    cursor = pos + len(cell)
            continue
        row = ln - 1 if header else ln
        cursor = 0
        for col, cell in enumerate(cells):
            if not cell:
                continue
            pos = line.find(cell, cursor)
            if pos < 0:
                continue
            key = header[col] if col < len(header) else f"col{col}"
            facts.append(Fact(sid, "cell", key, cell.strip(), off + pos, off + pos + len(cell), ln, row=row, column=col))
            cursor = pos + len(cell)
            if len(facts) >= limits.max_facts_per_source:
                return facts, err
    return facts, err


def scan_markdown(sid: str, text: str, starts: list[int], limits: ResourceLimits) -> list[Fact]:
    facts: list[Fact] = []
    in_fence = False
    table_header: list[str] = []
    table_row = 0
    for ln, off, line in _lines_with_offsets(text, starts, limits.max_lines_per_source):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            table_header = []
            continue
        if in_fence or not stripped:
            continue
        mh = _MD_HEADING.match(line) if stripped[0] == "#" else None
        if mh:
            table_header = []
            facts.append(Fact(sid, "heading", None, None, off + mh.start("text"), off + mh.end("text"), ln))
        elif stripped[0] == "|" and "|" in stripped[1:]:
            if _MD_TABLE_SEP.match(line):
                continue
            cells = [c for c in line.split("|")]
            # positions: walk the raw line
            cursor = 0
            texts: list[tuple[str, int]] = []
            for c in cells:
                pos = line.find(c, cursor)
                cursor = pos + len(c) + 1
                s = c.strip()
                if s:
                    texts.append((s, pos + (len(c) - len(c.lstrip()))))
            if not table_header:
                table_header = [t for t, _ in texts]
                table_row = 0
                for col, (t, p) in enumerate(texts):
                    facts.append(Fact(sid, "heading", t, None, off + p, off + p + len(t), ln, row=0, column=col))
            else:
                table_row += 1
                for col, (t, p) in enumerate(texts):
                    key = table_header[col] if col < len(table_header) else f"col{col}"
                    facts.append(Fact(sid, "cell", key, t, off + p, off + p + len(t), ln, row=table_row, column=col))
                if len(table_header) == 2 and len(texts) == 2:
                    # two-column tables are key/value tables in practice ("| replicas | 3 |"): also a key_value fact
                    (kt, kp), (vt, vp) = texts
                    facts.append(Fact(sid, "key_value", kt, vt, off + vp, off + vp + len(vt), ln, row=table_row, column=1,
                                      key_start=off + kp, key_end=off + kp + len(kt)))
        else:
            if not line.startswith((" ", "\t")):
                table_header = []
            # key: value lines inside prose docs (e.g. "Owner: platform-team") are facts too
            m = _YAML_KV.match(line) if ":" in line and stripped[0] not in "-*>" else None
            if m and m.group("val") and len(m.group("key")) <= 40:
                raw = m.group("val")
                vs = off + m.start("val")
                facts.append(Fact(sid, "key_value", _unquote(m.group("key")), _unquote(raw), vs, vs + len(raw), ln,
                                  key_start=off + m.start("key"), key_end=off + m.end("key")))
        if len(facts) >= limits.max_facts_per_source:
            break
    return facts


# ------------------------------------------------------------------------------------------------------ assembling ---
def _decode_one(name: str, path: str, origin: str, raw: bytes, mime: Optional[str], limits: ResourceLimits,
                warnings: list[SourceWarning], stats: dict[str, int]) -> Optional[DecodedSource]:
    digest = "sha256:" + sha256_hex(raw)
    media = media_type_for(path, mime)
    sid = _source_id(origin, path, digest)
    size = len(raw)
    if size == 0:
        warnings.append(SourceWarning("empty_source", path, "zero bytes"))
        return DecodedSource(SourceRef(sid, digest, path, origin, media, None, 0, False), "")
    if size > limits.max_entry_bytes:
        warnings.append(SourceWarning("entry_too_large", path, f"{size} > max_entry_bytes {limits.max_entry_bytes}"))
        return DecodedSource(SourceRef(sid, digest, path, origin, media, None, size, False), "")
    if stats["bytes_decoded"] + size > limits.max_total_bytes:
        warnings.append(SourceWarning("total_too_large", path, f"would exceed max_total_bytes {limits.max_total_bytes}"))
        return DecodedSource(SourceRef(sid, digest, path, origin, media, None, size, False), "")
    if _looks_binary(raw):
        warnings.append(SourceWarning("binary_skipped", path, "NUL byte, binary magic number, or control-byte density in the first 8 KiB"))
        return DecodedSource(SourceRef(sid, digest, path, origin, "binary", None, size, False), "")
    text, enc = decode_bytes(raw)
    if enc == "latin-1":
        warnings.append(SourceWarning("decode_fallback_latin1", path, "not valid UTF-8; latin-1 fallback (byte-exact offsets)"))
    if media == "unknown":
        warnings.append(SourceWarning("unknown_media_type", path, f"mime={mime!r}; scanned as plain text"))
        media_scan = "text"
    else:
        media_scan = media
    stats["bytes_decoded"] += size
    starts = line_starts(text)
    if len(starts) > limits.max_lines_per_source:
        warnings.append(SourceWarning("lines_truncated", path, f"{len(starts)} lines > {limits.max_lines_per_source}; facts limited"))
    src = DecodedSource(SourceRef(sid, digest, path, origin, media, enc, size, True), text, starts)
    facts: list[Fact] = []
    if media_scan == "yaml":
        facts = scan_yaml(sid, text, starts, limits)
    elif media_scan == "json":
        facts, err = scan_json(sid, text, starts, limits)
        if err:
            warnings.append(SourceWarning("json_malformed", path, err))
            facts = scan_json_lines(sid, text, starts, limits)   # best effort: `"key": value` lines (G2 burned repair)
    elif media_scan == "csv":
        facts, err = scan_csv(sid, text, starts, limits)
        if err:
            warnings.append(SourceWarning("csv_malformed", path, err))
    elif media_scan == "env":
        facts = scan_env(sid, text, starts, limits)
    elif media_scan == "markdown":
        facts = scan_markdown(sid, text, starts, limits)
    else:
        facts = scan_markdown(sid, text, starts, limits)      # headings/tables/kv lines are harmless on plain text
    if len(facts) >= limits.max_facts_per_source:
        warnings.append(SourceWarning("facts_truncated", path, f"capped at {limits.max_facts_per_source}"))
    src.facts = facts
    stats["facts"] += len(facts)
    return src


def _expand_zip(att: AttachmentInput, raw: bytes, limits: ResourceLimits, warnings: list[SourceWarning],
                stats: dict[str, int], depth: int) -> list[DecodedSource]:
    out: list[DecodedSource] = []
    base = normalize_safe_path(att.name) or "archive.zip"
    # the archive itself is a (non-decoded) container source, so a request naming "bundle.zip" can link to it (G2 burned repair)
    container_digest = "sha256:" + sha256_hex(raw)
    out.append(DecodedSource(SourceRef(_source_id(att.origin, base, container_digest), container_digest, base, att.origin, "zip",
                                       None, len(raw), False), ""))
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
        infos = zf.infolist()
    except (zipfile.BadZipFile, RuntimeError, ValueError) as e:
        warnings.append(SourceWarning("zip_invalid", base, f"{e.__class__.__name__}: {str(e)[:120]}"))
        return out
    if len(infos) > limits.max_zip_entries:
        warnings.append(SourceWarning("zip_too_many_entries", base, f"{len(infos)} > {limits.max_zip_entries}; listing stops"))
        infos = infos[: limits.max_zip_entries]
    seen: set[str] = set()
    for info in infos:
        stats["zip_entries_seen"] += 1
        member = f"{base}!{info.filename}"
        if info.is_dir():
            warnings.append(SourceWarning("zip_directory", member, "directory entry"))
            continue
        safe = normalize_safe_path(info.filename)
        if safe is None:
            warnings.append(SourceWarning("zip_unsafe_path", member, "absolute, drive-relative or parent-traversal path"))
            stats["zip_entries_skipped"] += 1
            continue
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            warnings.append(SourceWarning("zip_symlink", member, "symbolic link entry"))
            stats["zip_entries_skipped"] += 1
            continue
        if safe.lower() in seen:
            warnings.append(SourceWarning("zip_duplicate_path", member, "duplicate canonical path; first occurrence kept"))
            stats["zip_entries_skipped"] += 1
            continue
        seen.add(safe.lower())
        if info.compress_size and info.file_size / max(info.compress_size, 1) > limits.max_compression_ratio:
            warnings.append(SourceWarning("zip_compression_ratio", member,
                                          f"ratio {info.file_size / max(info.compress_size, 1):.0f} > {limits.max_compression_ratio}"))
            stats["zip_entries_skipped"] += 1
            continue
        if info.file_size > limits.max_entry_bytes:
            warnings.append(SourceWarning("entry_too_large", member, f"{info.file_size} > max_entry_bytes {limits.max_entry_bytes}"))
            stats["zip_entries_skipped"] += 1
            continue
        if safe.lower().endswith(_ARCHIVE_EXT):
            if not limits.allow_nested_archives or depth >= 1:
                warnings.append(SourceWarning("zip_nested_archive", member, "nested archive listed, not expanded"))
                stats["zip_entries_skipped"] += 1
                continue
        try:
            with zf.open(info) as fh:
                data = fh.read(limits.max_entry_bytes + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, ValueError) as e:
            warnings.append(SourceWarning("zip_invalid", member, f"{e.__class__.__name__}: {str(e)[:120]}"))
            stats["zip_entries_skipped"] += 1
            continue
        if len(data) > limits.max_entry_bytes:
            warnings.append(SourceWarning("entry_too_large", member, "declared size understated; read exceeded max_entry_bytes"))
            stats["zip_entries_skipped"] += 1
            continue
        path = f"{base}!{safe}"
        if safe.lower().endswith(".zip") and limits.allow_nested_archives and depth < 1:
            inner = AttachmentInput(name=path, mime_type="application/zip", content_bytes=data, origin=att.origin)
            out.extend(_expand_zip(inner, data, limits, warnings, stats, depth + 1))
            continue
        src = _decode_one(att.name, path, att.origin, data, None, limits, warnings, stats)
        if src is not None:
            out.append(src)
    return out


def load_sources(attachments: list[AttachmentInput], limits: ResourceLimits = ResourceLimits()) -> SourceSet:
    """Decode and scan every attachment under the limits. Never raises for content problems — they become warnings."""
    warnings: list[SourceWarning] = []
    stats = {"attachments": len(attachments), "sources": 0, "sources_decoded": 0, "bytes_decoded": 0, "facts": 0,
             "zip_entries_seen": 0, "zip_entries_skipped": 0}
    sources: list[DecodedSource] = []
    if len(attachments) > limits.max_attachments:
        warnings.append(SourceWarning("too_many_attachments", "<request>",
                                      f"{len(attachments)} > {limits.max_attachments}; extra attachments ignored"))
        attachments = attachments[: limits.max_attachments]
    for att in attachments:
        raw = att.raw()
        path = normalize_safe_path(att.name) or f"unsafe-name-{sha256_hex(att.name.encode('utf-8'))[:8]}"
        if path.startswith("unsafe-name-"):
            warnings.append(SourceWarning("zip_unsafe_path", att.name, "attachment name normalised to a safe placeholder"))
        media = media_type_for(path, att.mime_type)
        if media == "zip" or (att.content_bytes is not None and raw[:4] == b"PK\x03\x04"):
            sources.extend(_expand_zip(att, raw, limits, warnings, stats, 0))
            continue
        src = _decode_one(att.name, path, att.origin, raw, att.mime_type, limits, warnings, stats)
        if src is not None:
            sources.append(src)
    # canonical order: the graph must not depend on the order in which attachments were handed in
    sources.sort(key=lambda s: (s.ref.normalized_safe_path, s.ref.origin, s.ref.attachment_digest))
    warnings.sort(key=lambda w: (w.code, w.attachment, w.detail))
    stats["sources"] = len(sources)
    stats["sources_decoded"] = sum(1 for s in sources if s.ref.decoded)
    return SourceSet(sources, warnings, stats)
