"""AttachmentMap v1 — content-addressed, permission-aware structural map of already-ingested attachments (DCE-02).

Built only from ``zipingest.Ingest`` objects (SHA-verified, bounded, in-memory). Nothing in an attachment is executed
or evaluated; every byte stays labelled ``untrusted``. The map is immutable once built and repeatable for the same
authorized input: the same archives in the same order under the same scope yield the same ``map_id`` and JSON.

Coordinate system ``rendered_text_v1``: character offsets and 1-based lines refer to the *rendered* text of a file
(line endings normalized, HTML possibly converted) — the exact text whose hash is ``Entry.content_sha256``, i.e. the
text a model may later see. Every segment round-trips: ``file_text[start:end] == segment.text``.

Authorization: a map belongs to one ``Scope`` (tenant, user, request). Index keys are ``<scope key>:<content sha>``;
deduplication happens inside a scope only, and ``resolve``/``locate`` refuse a mismatching scope. A content hash is
never a credential: knowing a sha gives no access to another scope's map.
"""
from __future__ import annotations

import hashlib
import json
import math
import posixpath
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from jsonschema import Draft202012Validator

from .. import zipingest
from . import parsers

MAP_VERSION = "forge-2b.attachment-map.v1"
COORD_SYSTEM = "rendered_text_v1"
TRUST = "untrusted"
ROLE_HINTS = ("documentation", "config", "requirements", "tests", "results", "code", "tabular", "web", "changelog", "unknown")
REFERENCE_KINDS = ("relative_path", "import", "config_key")


class ScopeError(PermissionError):
    pass


@dataclass(frozen=True)
class Scope:
    tenant: str
    user: str
    request_id: str

    @property
    def key(self) -> str:
        return hashlib.sha256(f"{self.tenant}\x1f{self.user}\x1f{self.request_id}".encode()).hexdigest()[:24]


@dataclass(frozen=True)
class MapLimits:
    max_segments_per_file: int = 5000
    max_segments_total: int = 20000
    max_segment_chars: int = 20000      # longer segments are split by line; the split carries the parent context
    max_references: int = 5000
    max_aliases_per_segment: int = 16


@dataclass
class SourceFile:
    file_id: str                  # "a<i>/f<j>" — archive ordinal / entry ordinal (deterministic for the same input)
    archive_id: str
    archive_filename: str
    path: str
    mime: str
    encoding: str                 # Entry.rendered: text | latin1 | html_text | ""
    bytes: int
    sha256: str
    content_sha256: str
    status: str                   # INCLUDED | SKIPPED
    skip_reason: str
    lines: int
    integrity: str                # OK | MISSING | MISMATCH | "" (set by zipingest.parse_rendered when re-read)
    trust: str
    language: str
    role_hints: list[str]
    index_key: str                # "<scope key>:<content sha>" ("" for skipped)
    duplicate_of: str | None      # file_id of the canonical copy inside this scope
    segments: int                 # number of segments owned by this file (0 for duplicates/skipped)
    malformed: bool               # parser fell back to line segments


@dataclass
class Segment:
    seg_id: str                   # "<file_id>#s<n>"
    file_id: str
    kind: str
    start: int
    end: int
    start_line: int
    end_line: int
    text: str
    tokens_est: int               # ceil(chars / 4) — estimate, no tokenizer bundled
    context: dict[str, Any]
    aliases: list[str]
    malformed: bool = False


@dataclass
class Reference:
    from_seg: str
    kind: str                     # REFERENCE_KINDS
    target: str                   # path / module / key as written
    resolved_file: str | None     # file_id when verified
    verified: bool                # True = resolves to a file/key inside this map; False = heuristic (looks like one)


@dataclass
class Chunk:
    chunk_id: str
    file_id: str
    seg_ids: list[str]
    start: int
    end: int
    tokens_est: int
    context: dict[str, Any]
    oversize: bool = False


@dataclass
class AttachmentMap:
    version: str
    map_id: str
    coord_system: str
    scope_key: str
    files: list[SourceFile]
    segments: list[Segment]
    references: list[Reference]
    collisions: list[dict[str, Any]]      # same path in more than one archive
    bounds: dict[str, Any]
    model_calls: int = 0

    # --- lookups ------------------------------------------------------------------------------------------------
    def __post_init__(self) -> None:
        self._files = {f.file_id: f for f in self.files}
        self._segs = {s.seg_id: s for s in self.segments}
        self._by_file: dict[str, list[Segment]] = {}
        for s in self.segments:
            self._by_file.setdefault(s.file_id, []).append(s)
        self._texts: dict[str, str] = {}

    def _check(self, scope: Scope) -> None:
        if scope.key != self.scope_key:
            raise ScopeError("attachment map belongs to a different authorization scope")

    def file(self, file_id: str) -> SourceFile:
        return self._files[file_id]

    def text_of(self, file_id: str) -> str | None:
        """Rendered text of an INCLUDED file (None for skipped files or when the map was rebuilt from JSON)."""
        return self._texts.get(file_id)

    def canonical(self, file_id: str) -> str:
        f = self._files[file_id]
        return f.duplicate_of or file_id

    def segments_for(self, file_id: str) -> list[Segment]:
        return self._by_file.get(self.canonical(file_id), [])

    def resolve(self, seg_id: str, scope: Scope) -> dict[str, Any]:
        """Source-map round trip for a cited span: segment → file, archive, lines, offsets, verbatim text."""
        self._check(scope)
        s = self._segs[seg_id]
        f = self._files[s.file_id]
        text = self._texts.get(s.file_id)
        if text is not None and text[s.start:s.end] != s.text:
            raise ValueError(f"source map broken for {seg_id}")
        return {"seg_id": seg_id, "file_id": f.file_id, "path": f.path, "archive_id": f.archive_id, "archive_filename": f.archive_filename,
                "start": s.start, "end": s.end, "start_line": s.start_line, "end_line": s.end_line, "text": s.text,
                "content_sha256": f.content_sha256, "coord_system": self.coord_system, "trust": f.trust}

    def locate(self, path_or_file_id: str, line: int, scope: Scope) -> list[Segment]:
        """Segments covering ``line`` (1-based) of a file given by path or file_id; path matches every archive copy."""
        self._check(scope)
        ids = [path_or_file_id] if path_or_file_id in self._files else [f.file_id for f in self.files if f.path == path_or_file_id]
        out = [s for fid in ids for s in self.segments_for(fid) if s.start_line <= line <= s.end_line]
        return sorted(out, key=lambda s: (s.file_id, s.start, s.end))

    def files_by_path(self, path: str) -> list[SourceFile]:
        return [f for f in self.files if f.path == path]

    # --- renderings ---------------------------------------------------------------------------------------------
    def compact(self) -> str:
        """Structure only — paths, kinds, counts, key/column/heading/symbol names. Never values, rows or prose."""
        out = [f"attachment-map {self.map_id[:19]}… · {len(self.files)} files · {len(self.segments)} segments · {len(self.references)} refs · model_calls={self.model_calls}"]
        by_archive: dict[str, list[SourceFile]] = {}
        for f in self.files:
            by_archive.setdefault(f.archive_id, []).append(f)
        for aid, fs in by_archive.items():
            out.append(f"archive {fs[0].archive_filename} ({aid[:19]}…)")
            for f in fs:
                if f.status != "INCLUDED":
                    out.append(f"  {f.file_id} {f.path} SKIPPED:{f.skip_reason} {f.bytes}B")
                    continue
                if f.duplicate_of:
                    out.append(f"  {f.file_id} {f.path} duplicate_of={f.duplicate_of}")
                    continue
                segs = self._by_file.get(f.file_id, [])
                detail = _structure_summary(f, segs)
                flag = " MALFORMED" if f.malformed else ""
                out.append(f"  {f.file_id} {f.path} · {f.language} · {'/'.join(f.role_hints)} · {f.lines}L · {len(segs)} seg{flag}" + (f" · {detail}" if detail else ""))
        if self.collisions:
            out.append("collisions: " + "; ".join(f"{c['path']} in {','.join(c['file_ids'])}" for c in self.collisions))
        if self.bounds.get("hit"):
            out.append("bounds hit: " + ", ".join(self.bounds["hit"]))
        return "\n".join(out) + "\n"

    def chunks(self, budget_tokens: int = 400) -> list[Chunk]:
        """Group contiguous segments per file under a token budget. A segment is never split: a row, compound YAML
        value or code symbol larger than the budget becomes its own ``oversize`` chunk carrying its parent context."""
        out: list[Chunk] = []
        for f in self.files:
            segs = self._by_file.get(f.file_id, [])
            cur: list[Segment] = []
            cur_tok = 0
            n = 0

            def flush(oversize: bool = False) -> None:
                nonlocal cur, cur_tok, n
                if cur:
                    n += 1
                    out.append(Chunk(f"{f.file_id}#c{n}", f.file_id, [s.seg_id for s in cur], cur[0].start, cur[-1].end, cur_tok,
                                     _carry_context(cur[0]), oversize))
                cur, cur_tok = [], 0

            for s in segs:
                if s.tokens_est > budget_tokens:
                    flush()
                    cur, cur_tok = [s], s.tokens_est
                    flush(oversize=True)
                    continue
                if cur_tok + s.tokens_est > budget_tokens:
                    flush()
                cur.append(s)
                cur_tok += s.tokens_est
            flush()
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "map_id": self.map_id, "coord_system": self.coord_system, "scope_key": self.scope_key,
                "files": [asdict(f) for f in self.files], "segments": [asdict(s) for s in self.segments],
                "references": [asdict(r) for r in self.references], "collisions": self.collisions, "bounds": self.bounds,
                "model_calls": self.model_calls}

    def to_json(self, **kw: Any) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("sort_keys", True)
        return json.dumps(self.to_dict(), **kw)

    def validate(self) -> None:
        errors = sorted(VALIDATOR.iter_errors(self.to_dict()), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"AttachmentMap schema: {errors[0].message} at {'/'.join(map(str, errors[0].path))}")
        for s in self.segments:
            text = self._texts.get(s.file_id)
            if text is not None and text[s.start:s.end] != s.text:
                raise ValueError(f"segment {s.seg_id} does not round-trip")


# --- parse cache (content-addressed, scope-independent) ------------------------------------------------------------
# ``parsers.parse_file`` is a pure function of (rendered text, language); its result carries no scope, so caching it by
# content hash leaks nothing across scopes (the hash is never exposed as a credential, and the text itself must already
# be in hand to look it up). The cache is bounded by entries and by characters of cached text; it holds parsed
# structure only, never file text. It exists because a real proof package (60+ files, several large JSON dumps) costs
# ~1.3 s to parse cold, which blew the deterministic plan budget and silently sent every question to the legacy lane.
_PARSE_CACHE: "dict[tuple[str, str], tuple[list[parsers.Seg], list[int], int]]" = {}
_PARSE_CACHE_CHARS = 0
PARSE_CACHE_MAX_ENTRIES = 2048
PARSE_CACHE_MAX_CHARS = 48 * 1024 * 1024
PARSE_CACHE_STATS = {"hits": 0, "misses": 0}


def _parsed(text: str, lang: str, content_sha256: str) -> tuple[list[parsers.Seg], list[int], bool]:
    """(segments, line_starts, cached) for one file; cached entries are returned as-is (callers must not mutate)."""
    global _PARSE_CACHE_CHARS
    key = (content_sha256 or hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest(), lang)
    hitc = _PARSE_CACHE.get(key)
    if hitc is not None:
        _PARSE_CACHE[key] = _PARSE_CACHE.pop(key)   # LRU touch
        PARSE_CACHE_STATS["hits"] += 1
        return hitc[0], hitc[1], True
    PARSE_CACHE_STATS["misses"] += 1
    segs = parsers.parse_file(text, lang)
    starts = parsers.line_starts(text)
    while _PARSE_CACHE and (len(_PARSE_CACHE) >= PARSE_CACHE_MAX_ENTRIES or _PARSE_CACHE_CHARS + len(text) > PARSE_CACHE_MAX_CHARS):
        oldest = next(iter(_PARSE_CACHE))          # insertion order == LRU order thanks to the touch above
        _PARSE_CACHE_CHARS -= _PARSE_CACHE.pop(oldest)[2]
    if len(text) <= PARSE_CACHE_MAX_CHARS:
        _PARSE_CACHE[key] = (segs, starts, len(text))
        _PARSE_CACHE_CHARS += len(text)
    return segs, starts, False


def warm_parse_cache(ing: zipingest.Ingest) -> int:
    """Parse every included file of an ingest into the cache (used at upload time, off the question path). Returns the
    number of files parsed cold."""
    cold = 0
    for e in ing.entries:
        if e.status == "INCLUDED" and e.path in ing.files:
            _, _, cached = _parsed(ing.files[e.path], parsers.language_for(e.path, e.rendered), e.content_sha256)
            cold += int(not cached)
    return cold


def clear_parse_cache() -> None:
    global _PARSE_CACHE_CHARS
    _PARSE_CACHE.clear()
    _PARSE_CACHE_CHARS = 0
    PARSE_CACHE_STATS["hits"] = PARSE_CACHE_STATS["misses"] = 0


def _fair_allowances(counts: list[int], total: int) -> list[int]:
    """Per-file segment allowances summing to ≤ ``total``: small files keep every segment, the remainder is shared
    equally among the large ones (water-filling). Order-independent, so a big JSON dump early in the archive can no
    longer starve a small CSV or patch that sorts after it."""
    if sum(counts) <= total:
        return list(counts)
    allow = list(counts)
    remaining = total
    open_idx = list(range(len(counts)))
    while open_idx:
        share = remaining // len(open_idx)
        fits = [i for i in open_idx if counts[i] <= share]
        if not fits:
            for k, i in enumerate(sorted(open_idx)):
                allow[i] = share + (1 if k < remaining - share * len(open_idx) else 0)
            break
        for i in fits:
            allow[i] = counts[i]
            remaining -= counts[i]
        open_idx = [i for i in open_idx if i not in fits]
    return allow


# --- builder --------------------------------------------------------------------------------------------------------
def build_attachment_map(ingests: Iterable[zipingest.Ingest], scope: Scope, limits: MapLimits = MapLimits()) -> AttachmentMap:
    ingests = list(ingests)
    files: list[SourceFile] = []
    segments: list[Segment] = []
    texts: dict[str, str] = {}
    seen_content: dict[str, str] = {}      # index_key → canonical file_id (dedupe inside this scope only)
    hit: list[str] = []
    parsed: list[tuple[SourceFile, str, list[parsers.Seg], list[int]]] = []
    for ai, ing in enumerate(ingests, 1):
        for fi, e in enumerate(ing.entries, 1):
            fid = f"a{ai}/f{fi}"
            lang = parsers.language_for(e.path, e.rendered) if e.status == "INCLUDED" else ""
            sf = SourceFile(file_id=fid, archive_id=ing.archive_id, archive_filename=ing.filename, path=e.path, mime=e.mime,
                            encoding=e.rendered, bytes=e.bytes, sha256=e.sha256, content_sha256=e.content_sha256, status=e.status,
                            skip_reason=e.skip_reason, lines=e.lines, integrity=ing.integrity.get(e.path, ""), trust=TRUST, language=lang,
                            role_hints=[], index_key="", duplicate_of=None, segments=0, malformed=False)
            files.append(sf)
            if e.status != "INCLUDED" or e.path not in ing.files:
                sf.role_hints = ["unknown"]
                continue
            text = ing.files[e.path]
            texts[fid] = text
            sf.index_key = f"{scope.key}:{e.content_sha256}"
            if sf.index_key in seen_content:
                sf.duplicate_of = seen_content[sf.index_key]
                sf.role_hints = list(next(f for f in files if f.file_id == sf.duplicate_of).role_hints)
                continue
            seen_content[sf.index_key] = fid
            raw, starts, _cached = _parsed(text, lang, e.content_sha256)
            if len(raw) > limits.max_segments_per_file:
                raw = raw[: limits.max_segments_per_file]
                hit.append(f"{sf.file_id}:max_segments_per_file")
            sf.malformed = any(s.malformed for s in raw)
            sf.role_hints = _role_hints(e.path, lang, raw)
            parsed.append((sf, text, raw, starts))
    allowances = _fair_allowances([len(raw) for _, _, raw, _ in parsed], limits.max_segments_total)
    n_regular = 0   # segments counted against max_segments_total (coarse tail blocks are bounded by text size instead)
    for (sf, text, raw, starts), allow in zip(parsed, allowances):
        fid = sf.file_id
        kept = list(raw[:allow])
        if allow < len(raw):
            hit.append("max_segments_total")
            hit.append(f"{fid}:max_segments_total")
            # Source-map invariant: every non-blank line still belongs to a segment. The dropped fine-grained segments
            # are replaced by one coarse ``block`` over the tail (split by line length below), so a retrieval hit on a
            # truncated file still resolves to a verifiable pointer instead of an empty seg_id.
            tail_start = max((s.end for s in kept), default=0)
            if tail_start < len(text) and text[tail_start:].strip():
                kept.append(parsers.Seg("block", tail_start, len(text), {"truncated_tail": True, "dropped_segments": len(raw) - allow}))
        n = 0
        for seg in kept:
            for piece in _split_oversize(seg, text, starts, limits.max_segment_chars):
                is_tail = bool(piece.context.get("truncated_tail"))
                if n_regular >= limits.max_segments_total and not is_tail:
                    hit.append("max_segments_total")
                    break
                n_regular += 0 if is_tail else 1
                n += 1
                piece_text = text[piece.start:piece.end]
                segments.append(Segment(seg_id=f"{fid}#s{n}", file_id=fid, kind=piece.kind, start=piece.start, end=piece.end,
                                        start_line=parsers.line_of(starts, piece.start), end_line=parsers.line_of(starts, max(piece.start, piece.end - 1)),
                                        text=piece_text, tokens_est=max(1, math.ceil(len(piece_text) / 4)), context=dict(piece.context),
                                        aliases=list(piece.aliases[: limits.max_aliases_per_segment]), malformed=piece.malformed))
        sf.segments = n
    collisions = _collisions(files)
    refs = _references_cached(files, segments, limits.max_references, hit)
    digest = hashlib.sha256()
    digest.update(scope.key.encode())
    for f in files:
        digest.update(f"{f.archive_id}|{f.path}|{f.content_sha256}|{f.status}|{f.skip_reason}\n".encode())
    amap = AttachmentMap(version=MAP_VERSION, map_id="sha256:" + digest.hexdigest(), coord_system=COORD_SYSTEM, scope_key=scope.key, files=files,
                         segments=segments, references=refs, collisions=collisions,
                         bounds={"limits": asdict(limits), "hit": sorted(set(hit)), "ingest_limits": asdict(zipingest.Limits())}, model_calls=0)
    amap._texts = texts
    return amap


def _split_oversize(seg: parsers.Seg, text: str, starts: list[int], max_chars: int) -> list[parsers.Seg]:
    if seg.end - seg.start <= max_chars:
        return [seg]
    out: list[parsers.Seg] = []
    pos = seg.start
    part = 0
    while pos < seg.end:
        stop = min(seg.end, pos + max_chars)
        nl = text.rfind("\n", pos, stop)
        if nl > pos and stop < seg.end:
            stop = nl
        part += 1
        ctx = dict(seg.context)
        ctx.update(parent_split=True, parent_kind=seg.kind, parent_span=[seg.start, seg.end], part=part)
        out.append(parsers.Seg(seg.kind, pos, stop, ctx, seg.aliases, seg.malformed))
        pos = stop + (1 if stop < seg.end and text[stop:stop + 1] == "\n" else 0)
    return out


def _role_hints(path: str, lang: str, segs: list[parsers.Seg]) -> list[str]:
    hints: list[str] = []
    low = path.lower()
    base = posixpath.basename(low)
    parts = low.split("/")

    def add(h: str) -> None:
        if h not in hints:
            hints.append(h)

    if base.startswith("changelog") or "changelog" in base:
        add("changelog")
        add("documentation")
    if base.startswith("readme") or "docs" in parts[:-1] or "doc" in parts[:-1] or lang == "markdown":
        add("documentation")
    if lang in ("yaml", "json", "toml", "ini") or "config" in parts[:-1] or "conf" in parts[:-1]:
        add("config")
    if "tests" in parts[:-1] or "test" in parts[:-1] or base.startswith("test_") or base.rsplit(".", 1)[0].endswith("_test"):
        add("tests")
    if lang in ("csv", "tsv"):
        add("tabular")
        cols = next((s.context.get("columns") for s in segs if s.kind == "header"), None) or []
        if any(c.lower() in ("status", "result", "outcome", "passed", "verdict") for c in cols) or "result" in base or "report" in base:
            add("results")
    elif "result" in base or "report" in base:
        add("results")
    if lang in ("python", "javascript", "typescript", "shell", "sql"):
        add("code")
    if lang == "diff":
        add("code")
        add("changelog")
    if lang == "jsonl":
        add("tabular")
        if "result" in base or "report" in base or "cases" in base or "probes" in base:
            add("results")
    if lang == "html" or (lang == "text" and low.endswith((".html", ".htm"))) or "web" in parts[:-1]:
        add("web")
    if lang == "markdown" and any(s.kind == "heading" and re.search(r"requirement|must|shall|acceptance", s.context.get("title", ""), re.I) for s in segs):
        add("requirements")
    if not hints:
        add("unknown")
    return hints


def _collisions(files: list[SourceFile]) -> list[dict[str, Any]]:
    by_path: dict[str, list[SourceFile]] = {}
    for f in files:
        by_path.setdefault(f.path, []).append(f)
    out = []
    for path, fs in sorted(by_path.items()):
        archives = {f.archive_id for f in fs}
        if len(archives) > 1:
            out.append({"path": path, "file_ids": [f.file_id for f in fs], "identical_content": len({f.content_sha256 for f in fs}) == 1})
    return out


_PATH_TOKEN_RE = re.compile(r"(?<![\w/])((?:[\w.\-]+/)*[\w\-][\w.\-]*\.(?:md|markdown|ya?ml|json|jsonl|ndjson|csv|tsv|py|txt|html?|js|ts|toml|ini|cfg|bin|sh|sql|log|xml|rst|patch|diff))(?![\w/])", re.UNICODE)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


_REFS_CACHE: dict[str, tuple[list[Reference], bool]] = {}
REFS_CACHE_MAX = 32


def _references_cached(files: list[SourceFile], segments: list[Segment], max_refs: int, hit: list[str]) -> list[Reference]:
    """``_references`` is a pure function of the files' paths / roles / content and the segment list, none of which depends
    on the scope (file ids are positional, scope only enters ``index_key`` and ``map_id``). The same package is re-mapped
    for every question of a chat, and on a 68-file proof bundle this step alone is ~150 ms of a 1.5 s plan budget
    (live: K20 PLAN_TIMEOUT by 6 ms, after11), so the result is cached per content key and shared read-only."""
    h = hashlib.sha256(f"{max_refs}|{len(segments)}\n".encode())
    for f in files:
        h.update(f"{f.file_id}|{f.path}|{f.content_sha256}|{f.status}|{f.duplicate_of}|{','.join(f.role_hints)}|{f.segments}\n".encode())
    key = h.hexdigest()
    cached = _REFS_CACHE.get(key)
    if cached is None:
        before = len(hit)
        refs = _references(files, segments, max_refs, hit)
        cached = (refs, "max_references" in hit[before:])
        if len(_REFS_CACHE) >= REFS_CACHE_MAX:
            _REFS_CACHE.pop(next(iter(_REFS_CACHE)))
        _REFS_CACHE[key] = cached
    elif cached[1]:
        hit.append("max_references")
    return cached[0]


def _references(files: list[SourceFile], segments: list[Segment], max_refs: int, hit: list[str]) -> list[Reference]:
    by_path = {f.path: f.file_id for f in files if f.status == "INCLUDED" and not f.duplicate_of}
    by_base: dict[str, list[str]] = {}
    for f in files:
        if f.status == "INCLUDED":
            by_base.setdefault(posixpath.basename(f.path), []).append(f.file_id)
    stems = {posixpath.splitext(p)[0].replace("/", "."): fid for p, fid in by_path.items() if p.endswith(".py")}
    config_files = {f.file_id for f in files if "config" in f.role_hints}
    config_keys: dict[str, str] = {}
    for s in segments:
        if s.file_id in config_files and s.kind == "key" and s.context.get("key"):
            config_keys.setdefault(str(s.context["key"]).lower(), s.file_id)
    file_of = {f.file_id: f for f in files}
    refs: list[Reference] = []
    for s in segments:
        if len(refs) >= max_refs:
            hit.append("max_references")
            break
        own = file_of[s.file_id]
        if s.kind == "import":
            for mod in s.context.get("modules", []):
                if not mod:
                    continue
                target = mod.lstrip(".")
                fid = stems.get(target) or by_path.get(target.replace(".", "/") + ".py")
                if fid is None and mod.startswith("."):   # relative import / require('./x')
                    cand = posixpath.normpath(posixpath.join(posixpath.dirname(own.path), mod))
                    fid = next((v for k, v in sorted(by_path.items()) if k == cand or k.startswith(cand + ".")), None)
                refs.append(Reference(s.seg_id, "import", mod, fid, fid is not None))
            continue
        if s.kind in ("row", "header", "table_row", "table_header") and s.malformed:
            continue
        for m in _PATH_TOKEN_RE.finditer(s.text):
            tok = m.group(1)
            if tok == own.path:
                continue
            fid = by_path.get(tok)
            if fid is None:
                cands = by_base.get(posixpath.basename(tok), [])
                fid = cands[0] if len(cands) == 1 else None
            refs.append(Reference(s.seg_id, "relative_path", tok, fid, fid is not None))
        if own.file_id not in config_files and s.kind in ("paragraph", "list_item", "symbol", "docstring", "heading", "block", "element"):
            seen = set()
            for m in _IDENT_RE.finditer(s.text):
                ident = m.group(0).lower()
                if ident in seen or ident not in config_keys or config_keys[ident] == own.file_id:
                    continue
                seen.add(ident)
                refs.append(Reference(s.seg_id, "config_key", m.group(0), config_keys[ident], True))
    return refs


def _structure_summary(f: SourceFile, segs: list[Segment]) -> str:
    if f.language == "markdown":
        hs = [s.context.get("title", "") for s in segs if s.kind == "heading"]
        return ("headings: " + " > ".join(hs[:8])) if hs else ""
    if f.language in ("yaml", "json", "toml", "ini"):
        keys = [s.context.get("path") or s.context.get("pointer") or s.context.get("key") or "" for s in segs if s.kind == "key"]
        keys = [k for k in keys if k]
        return "keys: " + ", ".join(keys[:12]) + (" …" if len(keys) > 12 else "")
    if f.language in ("csv", "tsv"):
        h = next((s for s in segs if s.kind == "header"), None)
        return f"columns: {', '.join(h.context.get('columns', []))} · rows: {h.context.get('rows', 0)}" if h else ""
    if f.language in ("python", "javascript", "typescript"):
        syms = [s.context.get("symbol", "") for s in segs if s.kind == "symbol"]
        return ("symbols: " + ", ".join(syms[:12])) if syms else ""
    if f.language == "html":
        t = next((s.context.get("text_plain") for s in segs if s.context.get("tag") == "title"), None)
        return f"title: {t}" if t else ""
    if f.language == "diff":
        files = [s for s in segs if s.kind == "diff_file"]
        paths = [s.context.get("path", "") for s in files]
        added = sum(int(s.context.get("added", 0)) for s in files)
        removed = sum(int(s.context.get("removed", 0)) for s in files)
        return (f"changed files: {len(files)} (+{added} −{removed}): " + ", ".join(paths[:10]) + (" …" if len(paths) > 10 else "")) if files else ""
    if f.language == "jsonl":
        first = next((s for s in segs if s.kind == "record"), None)
        return f"records: {first.context.get('records', 0)} · keys: {', '.join(first.context.get('keys', [])[:10])}" if first else ""
    return ""


def _carry_context(s: Segment) -> dict[str, Any]:
    keep = ("heading_ancestry", "parent_keys", "columns", "path", "pointer", "symbol", "language", "tag")
    return {k: s.context[k] for k in keep if k in s.context}


# --- schema -----------------------------------------------------------------------------------------------------------
_STR = {"type": "string"}
_INT0 = {"type": "integer", "minimum": 0}
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["version", "map_id", "coord_system", "scope_key", "files", "segments", "references", "collisions", "bounds", "model_calls"],
    "properties": {
        "version": {"const": MAP_VERSION}, "map_id": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "coord_system": {"const": COORD_SYSTEM}, "scope_key": {"type": "string", "pattern": "^[0-9a-f]{24}$"},
        "files": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["file_id", "archive_id", "archive_filename", "path", "mime", "encoding", "bytes", "sha256", "content_sha256", "status",
                         "skip_reason", "lines", "integrity", "trust", "language", "role_hints", "index_key", "duplicate_of", "segments", "malformed"],
            "properties": {"file_id": {"type": "string", "pattern": "^a[0-9]+/f[0-9]+$"}, "archive_id": _STR, "archive_filename": _STR, "path": _STR,
                           "mime": _STR, "encoding": {"enum": ["", "text", "latin1", "html_text"]}, "bytes": _INT0, "sha256": _STR, "content_sha256": _STR,
                           "status": {"enum": ["INCLUDED", "SKIPPED"]}, "skip_reason": _STR, "lines": _INT0, "integrity": {"enum": ["", "OK", "MISSING", "MISMATCH"]},
                           "trust": {"const": TRUST}, "language": _STR, "role_hints": {"type": "array", "items": {"enum": list(ROLE_HINTS)}, "minItems": 1},
                           "index_key": _STR, "duplicate_of": {"type": ["string", "null"]}, "segments": _INT0, "malformed": {"type": "boolean"}}}},
        "segments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["seg_id", "file_id", "kind", "start", "end", "start_line", "end_line", "text", "tokens_est", "context", "aliases", "malformed"],
            "properties": {"seg_id": {"type": "string", "pattern": "^a[0-9]+/f[0-9]+#s[0-9]+$"}, "file_id": _STR, "kind": _STR, "start": _INT0, "end": _INT0,
                           "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}, "text": _STR, "tokens_est": {"type": "integer", "minimum": 1},
                           "context": {"type": "object"}, "aliases": {"type": "array", "items": _STR}, "malformed": {"type": "boolean"}}}},
        "references": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["from_seg", "kind", "target", "resolved_file", "verified"],
            "properties": {"from_seg": _STR, "kind": {"enum": list(REFERENCE_KINDS)}, "target": _STR, "resolved_file": {"type": ["string", "null"]}, "verified": {"type": "boolean"}}}},
        "collisions": {"type": "array", "items": {"type": "object", "required": ["path", "file_ids", "identical_content"]}},
        "bounds": {"type": "object", "required": ["limits", "hit", "ingest_limits"]},
        "model_calls": {"const": 0},
    },
}
VALIDATOR = Draft202012Validator(SCHEMA)
