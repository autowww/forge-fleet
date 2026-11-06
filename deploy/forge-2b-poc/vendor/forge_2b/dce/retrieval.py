"""DCE-03 retrieval over an AttachmentMap: SQLite FTS5 BM25 (line index with structural context) + exact
path/key/symbol/identifier matching + curated aliases + heading ancestry + explicit source scope, with honest
outcome classes. Zero model calls; originals are preserved verbatim for citations.

Outcome classes (owner decision Q4, 2026-11-05):
  FOUND              ≥1 ranked hit
  NOT_FOUND          zero hits AND the question carries a literal anchor (quoted text, identifier, number, path) that
                     appears nowhere in the fully readable in-scope text — literal absence is provable
  NOT_RETRIEVED      zero hits from a lexical search that cannot prove absence (conceptual question, paraphrase)
  SOURCE_UNREADABLE  every in-scope file is skipped / binary / integrity-mismatched
``Retriever(amap, use_aliases=..., use_structure=..., use_fts=...)`` exposes the ablation switches used by the evaluator.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from . import aliases as A
from .attachment_map import AttachmentMap

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of", "in", "on", "at", "to", "for", "from", "by", "with", "and", "or", "but",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "does", "do", "did", "it", "its", "this", "that", "these", "those",
    "there", "here", "please", "me", "my", "we", "our", "you", "your", "i", "can", "could", "would", "should", "will", "tell", "show", "give",
    "find", "list", "quote", "cite", "exact", "exactly", "according", "say", "says", "said", "about", "into", "as", "if", "then", "than", "so",
    "any", "all", "each", "every", "only", "just", "also", "not", "no", "yes", "file", "files", "archive", "zip", "attachment", "attached",
    "configured", "set", "used", "use", "uses", "using", "value", "values", "many", "much", "number", "count", "one", "two", "three",
    "service", "according", "per", "within", "inside", "between", "both", "either", "neither", "nor", "some", "has", "have", "had", "get",
    "wie", "viele", "welche", "welcher", "welches", "ist", "sind", "der", "die", "das", "und", "für", "quel", "quelle", "est", "les", "des", "pour",
    "какой", "какая", "какие", "сколько", "что", "кто", "где", "який", "яка", "які", "скільки", "що", "хто", "де", "jaki", "jaka", "jakie", "ile", "co",
}
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_QUOTED_RE = re.compile(r"[\"“”'‘’`]([^\"“”'‘’`]{2,80})[\"“”'‘’`]")
_IDENT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b[A-Z]{2,}_[A-Z0-9_]+\b|\b[a-z]+[A-Z][A-Za-z0-9]+\b")
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_PATH_RE = re.compile(r"[\w./\-\u00c0-\u024f\u0400-\u04ff\u3040-\u30ff\u4e00-\u9fff]+\.(?:md|txt|json|ya?ml|csv|py|js|ts|toml|xml|html?|sql|log|sh|ini|cfg|conf|rst|tsv)\b", re.I)


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def fold(s: str) -> str:
    """casefold + strip diacritics (ü→u, é→e) — the same normalization FTS5 unicode61 remove_diacritics applies."""
    return "".join(c for c in unicodedata.normalize("NFKD", norm(s)) if not unicodedata.combining(c))


@dataclass
class Hit:
    file_id: str
    path: str
    line: int
    seg_id: str
    text: str                       # verbatim line (citation-safe)
    score: float
    features: dict[str, float] = field(default_factory=dict)
    companion_of: str | None = None  # "<path>:<line>" when this hit is a CSV header added for a row hit


@dataclass
class RetrievalResult:
    status: str                      # FOUND | NOT_FOUND | NOT_RETRIEVED | SOURCE_UNREADABLE
    hits: list[Hit]
    query: str
    terms: list[str]
    expanded: dict[str, list[str]]   # canonical key → query phrases that triggered it
    typo_fixes: dict[str, str]
    anchors: list[str]
    scope_files: list[str]
    coverage: dict[str, Any]
    strategy: list[str]
    denominator: int                 # lines searched

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "hits": [asdict(h) for h in self.hits], "query": self.query, "terms": self.terms, "expanded": self.expanded,
                "typo_fixes": self.typo_fixes, "anchors": self.anchors, "scope_files": self.scope_files, "coverage": self.coverage,
                "strategy": self.strategy, "denominator": self.denominator}


@dataclass
class _Row:
    rowid: int
    file_id: str
    path: str
    line: int
    seg_id: str
    text: str
    kind: str
    keys: set[str]          # key / column / symbol names (normalized) attached to this line
    key_aliases: set[str]   # curated alias phrases for those keys (normalized)
    heading: str            # heading ancestry (normalized, space-joined)
    header_line: int | None # for CSV rows: the header line
    heading_line: int | None = None  # for markdown lines: the nearest enclosing heading line


class Retriever:
    def __init__(self, amap: AttachmentMap, *, use_aliases: bool = True, use_structure: bool = True, use_fts: bool = True,
                 alias_table: dict[str, tuple[str, ...]] | None = None):
        self.amap = amap
        self.use_aliases = use_aliases
        self.use_structure = use_structure
        self.use_fts = use_fts
        self.alias_table = alias_table if alias_table is not None else A.ALIASES
        self.rows: list[_Row] = []
        self.vocab: set[str] = set()
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE lines USING fts5(text, ctx, al, tokenize='unicode61 remove_diacritics 2')")
        self._build()

    # --- index -------------------------------------------------------------------------------------------------------
    def _build(self) -> None:
        cur = self.db.cursor()
        for f in self.amap.files:
            if f.status != "INCLUDED" or f.integrity in ("MISSING", "MISMATCH"):
                continue
            text = self.amap.text_of(f.file_id)
            if text is None:
                continue
            segs = self.amap.segments_for(f.file_id)
            header_line = next((s.start_line for s in segs if s.kind == "header"), None)
            heading_lines = sorted(s.start_line for s in segs if s.kind == "heading")
            for ln, line in enumerate(text.split("\n"), 1):
                if not line.strip():
                    continue
                covering = [s for s in segs if s.start_line <= ln <= s.end_line]
                keys: set[str] = set()
                heading_parts: list[str] = []
                kind = covering[0].kind if covering else "line"
                for s in covering:
                    c = s.context
                    for k in ("key", "symbol", "title"):
                        if c.get(k):
                            keys.add(norm(str(c[k])))
                    if s.kind in ("header", "table_header") or (s.kind in ("row", "table_row") and self.use_structure):
                        keys.update(norm(col) for col in c.get("columns", []) if col)
                    if s.kind in ("row", "table_row"):
                        cells = c.get("cells", {})
                        keys.update(norm(str(v)) for v in cells.values() if isinstance(v, str) and v and len(v) <= 40)
                    heading_parts += [norm(h) for h in c.get("heading_ancestry", [])]
                    heading_parts += [norm(str(p)) for p in c.get("parent_keys", []) if not str(p).startswith("[")]
                    if c.get("pointer"):
                        keys.update(norm(p) for p in str(c["pointer"]).split("/") if p and not p.isdigit())
                    if s.kind in ("key", "item") and c.get("path"):
                        keys.update(norm(p) for p in str(c["path"]).replace(".", " ").split() if not p.startswith("["))
                # identifiers inside the line itself (constants, snake_case) are exact anchors too
                keys.update(norm(m) for m in _IDENT_RE.findall(line))
                key_aliases: set[str] = set()
                if self.use_aliases:
                    for k in list(keys):
                        for phrase in A.expansions_for_key(k, self.alias_table)[1:]:
                            key_aliases.add(phrase)
                        for part in k.split("_"):
                            if part != k and part in self.alias_table:
                                key_aliases.update(A.expansions_for_key(part, self.alias_table)[1:])
                heading = " ".join(dict.fromkeys(heading_parts))
                ctx = " ".join(sorted(keys)) + " " + heading if self.use_structure else ""
                al = " ".join(sorted(key_aliases)) if self.use_aliases else ""
                rowid = len(self.rows) + 1
                seg_id = covering[0].seg_id if covering else ""
                self.rows.append(_Row(rowid, f.file_id, f.path, ln, seg_id, line, kind, keys if self.use_structure else set(),
                                      key_aliases, heading if self.use_structure else "", header_line if kind in ("row",) else None,
                                      next((hl for hl in reversed(heading_lines) if hl < ln), None)))
                cur.execute("INSERT INTO lines(rowid, text, ctx, al) VALUES (?,?,?,?)", (rowid, line, ctx, al))
                self.vocab.update(fold(w) for w in _WORD_RE.findall(line))
                self.vocab.update(fold(w) for k in keys for w in k.replace("_", " ").split())
        self.db.commit()

    # --- query analysis ----------------------------------------------------------------------------------------------
    def analyze(self, query: str) -> tuple[list[str], dict[str, list[str]], dict[str, str], list[str]]:
        q = norm(query)
        words = [w for w in _WORD_RE.findall(q) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
        terms = list(dict.fromkeys(words))
        expanded = A.expand(query, self.alias_table) if self.use_aliases else {}
        typo: dict[str, str] = {}
        for t in list(terms):
            ft = fold(t)
            if ft in self.vocab or len(ft) < 5 or ft.isdigit():
                continue
            cand = self._nearest(ft)
            if cand:
                typo[t] = cand
        anchors: list[str] = [m.group(1) for m in _QUOTED_RE.finditer(query)]
        anchors += _IDENT_RE.findall(query)
        anchors += [n for n in _NUM_RE.findall(query) if len(n) >= 2]
        anchors += [p for p in _PATH_RE.findall(query) if not any(p == f.path or f.path.endswith("/" + p) for f in self.amap.files)]
        return terms, expanded, typo, list(dict.fromkeys(anchors))

    def _rarity(self, key: str) -> float:
        """1.0 for a key seen on one line, decaying with the number of lines that carry it (IDF-like, deterministic)."""
        if not hasattr(self, "_df"):
            df: dict[str, int] = {}
            for r in self.rows:
                for k in r.keys:
                    df[k] = df.get(k, 0) + 1
            self._df = df
        import math
        return 1.0 / (1.0 + math.log(max(1, self._df.get(key, 1))))

    def _nearest(self, word: str) -> str | None:
        best: tuple[int, str] | None = None
        budget = 2 if len(word) >= 8 else 1
        for v in self.vocab:
            if abs(len(v) - len(word)) > budget or v[0] != word[0] or len(v) < 4:
                continue
            d = _edit_distance(word, v, budget)
            if d <= budget and (best is None or (d, v) < best):
                best = (d, v)
        return best[1] if best else None

    # --- search ------------------------------------------------------------------------------------------------------
    def search(self, query: str, *, scope_files: Iterable[str] | None = None, focus_files: Iterable[str] | None = None,
               exclude_files: Iterable[str] | None = None, max_hits: int = 8, max_chars: int = 3200) -> RetrievalResult:
        """``scope_files`` restricts the search (hard scope: the user named the file); ``focus_files`` only boosts (soft
        scope: a stem-like mention such as "the service" that *may* mean a file)."""
        terms, expanded, typo, anchors = self.analyze(query)
        strategy: list[str] = []
        scope = self._resolve_scope(scope_files, exclude_files)
        if focus_files and not scope_files:
            focus = self._resolve_scope(focus_files, None)["file_ids"]
            scope["explicit"] = focus
            if focus:
                strategy.append("focus:" + ",".join(sorted(self.amap.file(f).path for f in focus)))
        in_scope = {r.rowid: r for r in self.rows if r.file_id in scope["file_ids"]}
        search_terms = list(terms)
        for t, fix in typo.items():
            search_terms.append(fix)
        if self.use_aliases:
            for key, phrases in expanded.items():
                search_terms.append(key)
                search_terms += [w for p in A.expansions_for_key(key, self.alias_table) for w in p.split() if len(w) > 2]
            if expanded:
                strategy.append("aliases:" + ",".join(sorted(expanded)))
        if typo:
            strategy.append("typo:" + ",".join(f"{k}>{v}" for k, v in sorted(typo.items())))
        search_terms = [t for t in dict.fromkeys(search_terms) if t not in STOPWORDS]
        quoted_raw = _QUOTED_RE.findall(query)
        ident_raw = _IDENT_RE.findall(query)
        quoted = [norm(a) for a in quoted_raw]
        bm25: dict[int, float] = {}
        if self.use_fts and search_terms:
            strategy.append("fts5_bm25")
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in search_terms)
            try:
                for rowid, score in self.db.execute("SELECT rowid, bm25(lines, 1.0, 0.5, 0.4) FROM lines WHERE lines MATCH ? ", (match,)):
                    if rowid in in_scope:
                        bm25[rowid] = -float(score)
            except sqlite3.OperationalError:
                strategy.append("fts5_query_error")
        if self.use_structure:
            strategy.append("structure:keys/headings/identifiers")
        hits: list[Hit] = []
        key_terms = {fold(t) for t in terms} | {fold(v) for v in typo.values()}   # literal anchors only — alias expansions score via alias_key
        idents = {norm(i) for i in _IDENT_RE.findall(query)}
        nums = set(_NUM_RE.findall(query))
        explicit = scope["explicit"]
        bm_max = max(bm25.values(), default=0.0)
        alias_terms = {fold(t) for t in terms}
        term_words: dict[str, set[str]] = {t: {fold(t)} | ({fold(typo[t])} if t in typo else set()) for t in terms}
        if self.use_aliases:
            for key, phrases in expanded.items():
                words = {fold(w) for p in A.expansions_for_key(key, self.alias_table) for w in p.split() if len(w) > 2 and w not in STOPWORDS}
                for t in terms:
                    if any(t in p.split() for p in phrases):
                        term_words[t] |= words
        for rowid, r in in_scope.items():
            feats: dict[str, float] = {}
            base = bm25.get(rowid, 0.0)
            if base:
                feats["bm25"] = round(4.0 * base / bm_max, 3)   # scaled to [0, 4] so structure features stay comparable
            low = norm(r.text)
            lowf = fold(r.text)
            if self.use_structure:
                matched_keys = {k for k in r.keys if fold(k) in key_terms}
                if matched_keys:
                    feats["exact_key"] = round(3.0 * max(self._rarity(k) for k in matched_keys), 3)   # rare keys count more than a 6-row column
                if idents and any(i in low for i in idents):
                    feats["identifier"] = 2.5
                if r.heading and any(fold(t) in r.heading.split() for t in search_terms):
                    feats["heading"] = 1.0
            if self.use_aliases and r.key_aliases and (alias_terms & {fold(a) for a in r.key_aliases}):
                feats["alias_key"] = round(2.0 * max(self._rarity(k) for k in r.keys) if r.keys else 2.0, 3)
            if quoted and any(qv in low for qv in quoted):
                feats["quoted"] = 3.0
            if nums and any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w.])", r.text) for n in nums):
                feats["number"] = 1.0
            if not self.use_fts and any(fold(t) in lowf for t in search_terms):
                feats["substring"] = 1.0
            if terms:   # a line that covers more distinct question words (literally or via a curated alias) beats a structural line matching one
                covered = sum(1 for t in terms if any(w in lowf for w in term_words[t]))
                if covered:
                    feats["term_coverage"] = round(3.0 * covered / len(terms), 3)
            if explicit and r.file_id in explicit:
                feats["path_scope"] = 2.0 if feats else (0.5 if scope_files else 0.0)
            score = sum(feats.values())
            if score > 0:
                hits.append(Hit(r.file_id, r.path, r.line, r.seg_id, r.text, round(score, 3), feats))
        hits.sort(key=lambda h: (-h.score, h.path, h.line))
        out: list[Hit] = []
        used = 0
        seen: set[tuple[str, int]] = set()
        for h in hits:
            if len(out) >= max_hits or used + len(h.text) > max_chars:
                break
            if (h.file_id, h.line) in seen:
                continue
            out.append(h)
            seen.add((h.file_id, h.line))
            used += len(h.text)
            r = in_scope[next(rid for rid, rr in in_scope.items() if rr.file_id == h.file_id and rr.line == h.line)]
            companion = None
            if self.use_structure and r.header_line and (h.file_id, r.header_line) not in seen:
                companion = (r.header_line, "header_for_row", "csv_header_companion")
            elif self.use_structure and r.heading_line and len(out) <= 3 and (h.file_id, r.heading_line) not in seen and r.kind != "heading":
                companion = (r.heading_line, "heading_for_line", "heading_companion")   # dated/section heading is context for the top hits
            if companion and len(out) < max_hits:
                hr = next(rr for rr in in_scope.values() if rr.file_id == h.file_id and rr.line == companion[0])
                out.append(Hit(hr.file_id, hr.path, hr.line, hr.seg_id, hr.text, h.score, {companion[1]: 1.0}, companion_of=f"{h.path}:{h.line}"))
                seen.add((h.file_id, hr.line))
                used += len(hr.text)
                if companion[2] not in strategy:
                    strategy.append(companion[2])
        coverage = {"files_in_scope": len(scope["file_ids"]), "files_total_included": sum(1 for f in self.amap.files if f.status == "INCLUDED"),
                    "files_unreadable_in_scope": scope["unreadable"], "lines_searched": len(in_scope), "lines_indexed": len(self.rows),
                    "explicit_scope": bool(explicit), "excluded": sorted(scope["excluded"])}
        strong = [a for a in anchors if a in quoted_raw or a in ident_raw]
        if strong and not scope["unreadable"] and in_scope and all(not any(norm(a) in norm(r.text) for r in in_scope.values()) for a in strong):
            # the user asked about a literal (quoted text / identifier) that occurs nowhere in fully readable scope:
            # filler-word hits would be misleading evidence → literal absence is the answer
            out = []
            status = "NOT_FOUND"
            strategy.append("exhaustive_literal_scan")
        elif out:
            status = "FOUND"
        elif scope["unreadable"] and not scope["file_ids"]:
            status = "SOURCE_UNREADABLE"
        elif anchors and not scope["unreadable"] and all(not any(norm(a) in norm(r.text) for r in in_scope.values()) for a in anchors):
            status = "NOT_FOUND"
            strategy.append("exhaustive_literal_scan")
        else:
            status = "NOT_RETRIEVED"
        return RetrievalResult(status, out, query, terms, expanded, typo, anchors, sorted(scope["paths"]), coverage, strategy, len(in_scope))

    def _resolve_scope(self, scope_files, exclude_files) -> dict[str, Any]:
        included = [f for f in self.amap.files if f.status == "INCLUDED"]
        unreadable = 0
        explicit: set[str] = set()
        excluded: set[str] = set()
        if scope_files:
            wanted = set()
            for name in scope_files:
                matches = [f for f in self.amap.files if f.path == name or f.path.endswith("/" + name) or f.file_id == name]
                if not matches:
                    matches = [f for f in self.amap.files if f.path.rsplit("/", 1)[-1].rsplit(".", 1)[0] == name.rsplit(".", 1)[0]]
                for f in matches:
                    if f.status != "INCLUDED" or f.integrity in ("MISSING", "MISMATCH") or self.amap.text_of(f.file_id) is None:
                        unreadable += 1
                    else:
                        wanted.add(f.file_id)
            explicit = wanted
            files = [f for f in included if f.file_id in wanted]
        else:
            files = included
        if exclude_files:
            for name in exclude_files:
                for f in list(files):
                    if f.path == name or f.path.endswith("/" + name) or f.file_id == name or f.path.rsplit("/", 1)[-1].rsplit(".", 1)[0] == str(name).rsplit(".", 1)[0]:
                        files.remove(f)
                        excluded.add(f.path)
        return {"file_ids": {f.file_id for f in files}, "paths": {f.path for f in files}, "unreadable": unreadable, "explicit": explicit, "excluded": excluded}


def _edit_distance(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > cap:
            return cap + 1
        prev = cur
    return prev[-1]
