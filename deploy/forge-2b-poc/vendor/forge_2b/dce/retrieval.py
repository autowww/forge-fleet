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

import hashlib
import re
import sqlite3
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from . import aliases as A
from .attachment_map import AttachmentMap
from .lexicon import SHAPE_WORDS

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "of", "in", "on", "at", "to", "for", "from", "by", "with", "and", "or", "but",
    "what", "which", "who", "whom", "whose", "when", "where", "why", "how", "does", "do", "did", "it", "its", "this", "that", "these", "those",
    "there", "here", "please", "me", "my", "we", "our", "you", "your", "i", "can", "could", "would", "should", "will", "tell", "show", "give",
    "find", "list", "quote", "cite", "exact", "exactly", "according", "say", "says", "said", "about", "into", "as", "if", "then", "than", "so",
    "any", "all", "each", "every", "only", "just", "also", "not", "no", "yes", "file", "files", "archive", "zip", "attachment", "attached",
    "configured", "set", "used", "use", "uses", "using", "value", "values", "many", "much", "number", "count", "one", "two", "three",
    "service", "according", "per", "within", "inside", "between", "both", "either", "neither", "nor", "some", "has", "have", "had", "get",
    "under", "upon", "via", "against", "during",   # scope prepositions: "under rule 27" is about rule 27, not about `under` (live M29 G1R3E)
    "wie", "viele", "welche", "welcher", "welches", "ist", "sind", "der", "die", "das", "und", "für", "quel", "quelle", "est", "les", "des", "pour",
    "какой", "какая", "какие", "сколько", "что", "кто", "где", "який", "яка", "які", "скільки", "що", "хто", "де", "jaki", "jaka", "jakie", "ile", "co",
}
_WORD_RE = re.compile(r"\w+", re.UNICODE)
# language name (folded) -> ISO 639-1 code, the form evaluation reports use ("languages en 70 · uk 39"); applied only
# when the code is a token of the indexed files, so "it"/"no"/"is" can never be injected into an unrelated question
LANGUAGE_CODES = {"english": "en", "ukrainian": "uk", "german": "de", "french": "fr", "spanish": "es", "polish": "pl", "italian": "it",
                  "dutch": "nl", "russian": "ru", "portuguese": "pt", "japanese": "ja", "chinese": "zh", "czech": "cs", "swedish": "sv",
                  "norwegian": "no", "danish": "da", "finnish": "fi", "turkish": "tr", "arabic": "ar", "hebrew": "he", "korean": "ko",
                  "hindi": "hi", "greek": "el", "hungarian": "hu", "romanian": "ro", "bulgarian": "bg"}
_QUOTED_RE = re.compile(r"[\"“”'‘’`]([^\"“”'‘’`]{2,80})[\"“”'‘’`]")
_IDENT_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|\b[A-Z]{2,}_[A-Z0-9_]+\b|\b[a-z]+[A-Z][A-Za-z0-9]+\b")
_NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_CODE_RE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{2,8}\b")   # short codes: B1, E040, G1R3A — exact anchors like identifiers
_WHO_RE = re.compile(r"^\s*(who|whom|whose)\b", re.I)
_SCALAR_LEAF_RE = re.compile(r"""^\s*["'`]?[\w.\-/ ]+["'`]?\s*[:=]\s*(true|false|null|none|yes|no|-?\d+(?:\.\d+)?)\s*,?\s*$""", re.I)
_STEM_SUFFIXES = ("ings", "ing", "ers", "er", "ed", "es", "ly", "s")
# irregular past participles common in engineering prose, mapped to the prefix their base form shares with its inflections
_IRREGULAR_STEMS = {"frozen": "freez", "froze": "freez", "chosen": "choos", "chose": "choos", "written": "writ", "wrote": "writ", "built": "build",
                    "held": "hold", "kept": "keep", "taken": "take", "took": "take", "made": "make", "sent": "send", "broken": "break", "broke": "break"}


def stems_of(word: str) -> set[str]:
    """Light, deterministic suffix stripping for words of six letters or more: ``labelled`` → ``labell`` so that the
    question word meets ``labeller`` in the text (live K16, 2026-11-06). Stems shorter than five letters are dropped,
    so ``caused`` / ``running`` / ``cases`` add nothing; the stem is used as a prefix (FTS) and a substring (coverage)."""
    w = fold(word)
    out = set()
    if w in _IRREGULAR_STEMS:
        out.add(_IRREGULAR_STEMS[w])   # `frozen` meets `freeze` / `FREEZE.txt` (live L14 G1R3D, 2026-11-07)
    if len(w) < 6 or w.isdigit():
        return out
    for suf in _STEM_SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 5:
            out.add(w[: -len(suf)])
    return out - {w}
# value shapes for the head noun of a "which / what <noun>" question (shared with dag.typed_label_value)
VALUE_RE_FOR = {"commit": r"\b[0-9a-f]{7,40}\b", "hash": r"\b[0-9a-f]{7,64}\b", "sha": r"\b[0-9a-f]{7,64}\b", "version": r"\bv?\d+\.\d+(?:\.\d+)*(?:[-+][\w.]+)?\b",
                "date": r"\b\d{4}-\d{2}-\d{2}\b", "port": r"\b\d{2,5}\b", "tag": r"\bv?\d+\.\d+(?:\.\d+)*\b", "branch": r"\b[\w][\w./-]{2,}\b"}
_RULE_ROW_RE = re.compile(r"^\s*(?:\|?\s*:?-{2,}:?\s*)+\|?\s*$|^\s*[-=*_]{3,}\s*$")   # markdown table rule / horizontal rule
_LABEL_LINE_RE = re.compile(r"^\s*[-*]?\s*\**([A-Za-z][A-Za-z_ \-]{2,40}?)\**\s*:\s+\S")   # `candidate_frozen_at: 21d608c` is a label too (live M13 G1R3E)   # `Labeller: …`, `- **Owner**: …`
_SOURCE_EXT_RE = re.compile(r"\.(?:py|js|ts|tsx|jsx|java|go|rs|c|cc|cpp|h|hpp|cs|rb|php|sh|bash|sql|patch|diff)$", re.I)   # program source (a patch is code)
_WHY_Q_RE = re.compile(r"^\s*(?:why|for what reason|what (?:is|was) the reason|how come)\b", re.I)
_CAUSAL_RE = re.compile(r"\b(?:because|due to|since|as a result|owing to|caused by|reason|therefore|so that|failed|fails|failure|led to|given that)\b|\(\s*\d", re.I)
_DUMP_EXT_RE = re.compile(r"\.(?:json|jsonl|ndjson|csv|tsv|log)$", re.I)   # machine result dumps — many near-identical leaves per case
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
    # precomputed normal forms (pure functions of the fields above; computed once at index build, not per question)
    textn: str = ""         # norm(text)
    textf: str = ""         # fold(text)
    keysf: frozenset[str] = frozenset()        # {fold(k) for k in keys}
    key_aliasesf: frozenset[str] = frozenset() # {fold(a) for a in key_aliases}
    heading_words: frozenset[str] = frozenset()  # set(heading.split())
    scope_label: frozenset[str] = frozenset()    # an indented `label:` line's parent label words (plain-text blocks); empty otherwise


class _Index:
    """The built line index: rows, vocabulary and the FTS5 connection. Shared between Retrievers for maps with the
    same content (the index depends on file texts and segments only, never on the scope), so the per-question cost
    of a large package is a dictionary lookup instead of a multi-second rebuild. The connection is created with
    ``check_same_thread=False`` and every query takes ``lock``: the plan stage runs in worker threads."""

    def __init__(self) -> None:
        self.rows: list[_Row] = []
        self.rows_per_file: dict[str, int] = {}
        self.rows_by_file: dict[str, list[_Row]] = {}   # line order, for section-body / table-row companions
        self.vocab: set[str] = set()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE lines USING fts5(text, ctx, al, tokenize='unicode61 remove_diacritics 2')")
        self.lock = threading.Lock()


_INDEX_CACHE: "dict[str, _Index]" = {}
INDEX_CACHE_MAX = 32
INDEX_CACHE_STATS = {"hits": 0, "misses": 0}


def _content_key(amap: AttachmentMap, flags: tuple) -> str:
    h = hashlib.sha256(repr(flags).encode())
    for f in amap.files:
        # ``_build`` only distinguishes "indexed" from "excluded" (MISSING / MISMATCH): the zip-time map carries
        # integrity "" and the chat-time map rebuilt from the rendered page carries "OK" — same index, same key, or the
        # warm-at-ingest index is never hit and the first question of every chat pays the cold build (live: K01/K02 PLAN_TIMEOUT)
        indexed = f.status == "INCLUDED" and f.integrity not in ("MISSING", "MISMATCH")
        h.update(f"{f.file_id}|{f.path}|{f.content_sha256}|{int(indexed)}|{f.duplicate_of}|{f.segments}\n".encode())
    return h.hexdigest()


def clear_index_cache() -> None:
    _INDEX_CACHE.clear()
    INDEX_CACHE_STATS["hits"] = INDEX_CACHE_STATS["misses"] = 0


class Retriever:
    def __init__(self, amap: AttachmentMap, *, use_aliases: bool = True, use_structure: bool = True, use_fts: bool = True,
                 alias_table: dict[str, tuple[str, ...]] | None = None):
        self.amap = amap
        self.use_aliases = use_aliases
        self.use_structure = use_structure
        self.use_fts = use_fts
        self.narrow_candidates = True   # FTS pre-selection of rows worth scoring (see ``search``); False = full sweep (tests, A/B)
        self.alias_table = alias_table if alias_table is not None else A.ALIASES
        key = _content_key(amap, (use_aliases, use_structure, use_fts, id(self.alias_table) if alias_table is not None else "default"))
        idx = _INDEX_CACHE.get(key)
        if idx is None:
            INDEX_CACHE_STATS["misses"] += 1
            idx = _Index()
            self._index = idx
            self._build()
            while len(_INDEX_CACHE) >= INDEX_CACHE_MAX:
                _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
            _INDEX_CACHE[key] = idx
        else:
            INDEX_CACHE_STATS["hits"] += 1
            _INDEX_CACHE[key] = _INDEX_CACHE.pop(key)   # LRU touch
            self._index = idx

    @property
    def rows(self) -> list[_Row]:
        return self._index.rows

    @property
    def vocab(self) -> set[str]:
        return self._index.vocab

    @property
    def db(self) -> sqlite3.Connection:
        return self._index.db

    # --- index -------------------------------------------------------------------------------------------------------
    def _build(self) -> None:
        cur = self.db.cursor()
        batch: list[tuple[int, str, str, str]] = []
        for f in self.amap.files:
            if f.status != "INCLUDED" or f.integrity in ("MISSING", "MISMATCH"):
                continue
            text = self.amap.text_of(f.file_id)
            if text is None:
                continue
            segs = self.amap.segments_for(f.file_id)
            header_line = next((s.start_line for s in segs if s.kind == "header"), None)
            heading_lines = sorted(s.start_line for s in segs if s.kind == "heading")
            table_headers = sorted(s.start_line for s in segs if s.kind == "table_header")   # markdown: nearest header above a row
            # sweep: segments become active at start_line and drop out after end_line — O(lines + segments) instead
            # of the O(lines × segments) scan that made a 5000-leaf JSON dump cost seconds per file
            by_start: dict[int, list] = {}
            order = {id(s): i for i, s in enumerate(segs)}
            for s in segs:
                by_start.setdefault(s.start_line, []).append(s)
            active: list = []
            label_stack: list[tuple[int, str]] = []   # (indent, label) of the `label:` lines above, within the current blank-line block
            for ln, line in enumerate(text.split("\n"), 1):
                if ln in by_start:
                    active.extend(by_start[ln])
                if active:
                    active = [s for s in active if s.end_line >= ln]
                if not line.strip():
                    label_stack = []
                    continue
                covering = sorted(active, key=lambda s: order[id(s)]) if active else []   # same order as the original scan
                keys: set[str] = set()
                heading_parts: list[str] = []
                kind = covering[0].kind if covering else "line"
                # an indented `label: value` line in a plain-text block belongs to the less-indented label above it the way a
                # table row belongs to its header: `  frozen in commit: 83ab46b` under `Sealed set: …` is the sealed set's
                # commit, not the file's (live L14 G1R3D, lab after06 + production v2_granite02, 2026-11-07 — it outranked
                # the top-level `Candidate commit: 620c217` for "Which commit is the frozen candidate?")
                scope_label: frozenset[str] = frozenset()
                indent = len(line) - len(line.lstrip())
                lm_line = _LABEL_LINE_RE.match(line) if kind in ("paragraph", "line") else None
                while label_stack and label_stack[-1][0] >= indent:
                    label_stack.pop()
                if lm_line is not None:
                    if indent > 0 and label_stack:
                        scope_label = frozenset(fold(w) for w in _WORD_RE.findall(label_stack[-1][1]) if len(w) > 1) - STOPWORDS
                        heading_parts.append(norm(label_stack[-1][1]))
                    label_stack.append((indent, lm_line.group(1)))
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
                row_keys = keys if self.use_structure else set()
                row_heading = heading if self.use_structure else ""
                self._index.rows_per_file[f.file_id] = self._index.rows_per_file.get(f.file_id, 0) + 1
                self.rows.append(_Row(rowid, f.file_id, f.path, ln, seg_id, line, kind, row_keys,
                                      key_aliases, row_heading,
                                      header_line if kind == "row" else next((hl for hl in reversed(table_headers) if hl < ln), None) if kind == "table_row" else None,
                                      next((hl for hl in reversed(heading_lines) if hl < ln), None),
                                      textn=norm(line), textf=fold(line), keysf=frozenset(fold(k) for k in row_keys),
                                      key_aliasesf=frozenset(fold(a) for a in key_aliases), heading_words=frozenset(row_heading.split()),
                                      scope_label=scope_label if self.use_structure else frozenset()))
                self._index.rows_by_file.setdefault(f.file_id, []).append(self.rows[-1])
                batch.append((rowid, line, ctx, al))
                self.vocab.update(fold(w) for w in _WORD_RE.findall(line))
                self.vocab.update(fold(w) for k in keys for w in k.replace("_", " ").split())
        cur.executemany("INSERT INTO lines(rowid, text, ctx, al) VALUES (?,?,?,?)", batch)
        self.db.commit()

    # --- query analysis ----------------------------------------------------------------------------------------------
    def analyze(self, query: str) -> tuple[list[str], dict[str, list[str]], dict[str, str], list[str]]:
        q = norm(query)
        words = [w for w in _WORD_RE.findall(q) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
        terms = list(dict.fromkeys(words))
        # the request verb and output-shape words ("summarize … in two sentences") name nothing in the files; dropped when
        # anything else remains, so they cannot own the ranking (live K41 2026-11-06)
        content = [t for t in terms if fold(t) not in SHAPE_WORDS]
        if content:
            terms = content
        expanded = A.expand(query, self.alias_table) if self.use_aliases else {}
        typo: dict[str, str] = {}
        for t in list(terms):
            ft = fold(t)
            # a language name in the question, its ISO 639-1 code in the files ("Ukrainian" ↔ `uk 39`, live K19 2026-11-06):
            # the code is a literal variant of the word, like a typo repair, but only when the files actually use it
            code = LANGUAGE_CODES.get(ft)
            if code and code in self.vocab:
                typo[t] = code
                continue
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

    def _label_body(self, r: "_Row", literal_f: set[str], idents: set[str], nums: set[str], seen: set[tuple[str, int]],
                    *, max_lines: int = 3, window: int = 14) -> list[tuple[int, str, str]]:
        """Body lines labelled by a heading / table header row: the rows that follow in the same file until the next
        heading (headings) or until the table ends (header rows), bounded by ``window``. Up to ``max_lines``; rows that
        mention a literal question word, identifier or number rank first, then document order."""
        rows = self._index.rows_by_file.get(r.file_id, [])
        i = next((k for k, rr in enumerate(rows) if rr.line == r.line), None)
        if i is None:
            return []
        is_table = r.kind in ("table_header", "header")
        label, strat = ("rows_for_header", "table_rows_companion") if is_table else ("section_body", "heading_body_companion")
        cands: list[_Row] = []
        for rr in rows[i + 1:]:
            if rr.line - r.line > window:
                break
            if _RULE_ROW_RE.match(rr.text):
                continue   # the `|---|` rule between a markdown header and its rows (kind block)
            if is_table:
                if rr.kind not in ("table_row", "row"):
                    break
            elif rr.kind == "heading":
                break
            if (rr.file_id, rr.line) in seen:
                continue
            cands.append(rr)
        if not cands:
            return []

        def rank(rr: "_Row") -> tuple[int, int]:
            lowf = rr.textf
            hit = any(w in lowf for w in literal_f) or any(i_ in rr.textn for i_ in idents) or \
                any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w.])", rr.text) for n in nums)
            return (0 if hit else 1, rr.line)

        limit = max_lines + 2 if is_table else max_lines   # a small table is cheap and often needs every row ("highest p95")
        return [(rr.line, label, strat) for rr in sorted(cands, key=rank)[:limit]]

    # --- search ------------------------------------------------------------------------------------------------------
    def search(self, query: str, *, scope_files: Iterable[str] | None = None, focus_files: Iterable[str] | None = None,
               exclude_files: Iterable[str] | None = None, max_hits: int = 8, max_chars: int = 3200) -> RetrievalResult:
        """``scope_files`` restricts the search (hard scope: the user named the file); ``focus_files`` only boosts (soft
        scope: a stem-like mention such as "the service" that *may* mean a file)."""
        terms, expanded, typo, anchors = self.analyze(query)
        strategy: list[str] = []
        why_question = bool(_WHY_Q_RE.match(query))
        q_words = {fold(w) for w in _WORD_RE.findall(norm(query).lower())}
        if why_question:
            strategy.append("why_question")
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
        # Only literal question words (plus typo repairs) go to FTS. The paraphrase path is the ``al`` column: a row
        # whose key is `status` carries "verdict" in ``al``, so the literal word already finds it at alias weight;
        # also querying the alias key `status` itself matched the *text* of every `"status": "ok"` leaf at full
        # weight — in the G1R3A package (thousands of such leaves) `"verdict": "HOLD"` ranked 411th (live K02,
        # 2026-11-06) and the bm25 ceiling belonged to a one-token leaf.
        literal_terms = [t for t in dict.fromkeys([*terms, *typo.values()]) if t not in STOPWORDS]
        quoted_raw = _QUOTED_RE.findall(query)
        ident_raw = _IDENT_RE.findall(query)
        quoted = [norm(a) for a in quoted_raw]
        bm25: dict[int, float] = {}
        if self.use_fts and literal_terms:
            strategy.append("fts5_bm25")
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in literal_terms)
            try:
                with self._index.lock:
                    fts_rows = self.db.execute("SELECT rowid, bm25(lines, 1.0, 0.5, 0.4) FROM lines WHERE lines MATCH ? ", (match,)).fetchall()
                for rowid, score in fts_rows:
                    if rowid in in_scope:
                        bm25[rowid] = -float(score)
            except sqlite3.OperationalError:
                strategy.append("fts5_query_error")
        if self.use_structure:
            strategy.append("structure:keys/headings/identifiers")
        hits: list[Hit] = []
        key_terms = {fold(t) for t in terms} | {fold(v) for v in typo.values()}   # literal anchors only — alias expansions score via alias_key
        idents = {norm(i) for i in _IDENT_RE.findall(query)} | {norm(c) for c in _CODE_RE.findall(query)}
        nums = set(_NUM_RE.findall(query))
        explicit = scope["explicit"]
        bm_max = max(bm25.values(), default=0.0)
        alias_terms = {fold(t) for t in terms}
        literal_f = {fold(t) for t in literal_terms}
        term_words: dict[str, set[str]] = {t: {fold(t)} | ({fold(typo[t])} if t in typo else set()) | stems_of(t) for t in terms}
        stem_terms = sorted({st for t in terms for st in stems_of(t)})
        q_forms = {fold(w) for w in _WORD_RE.findall(norm(query))} | set(stem_terms) | set().union(*term_words.values()) if terms else {fold(w) for w in _WORD_RE.findall(norm(query))}
        # the head noun of a "which / what <noun>" question names the *type* of the value asked (commit, version, date), not
        # its label: `candidate_commit:` must not become the label line for "Which commit froze the blind set?" (live K17
        # regression 2026-11-06 — the label match was added for `candidate_frozen_at:` on "Which commit is the frozen candidate?")
        head_m = re.match(r"^\s*(?:which|what|in which|in what)\s+(?:is\s+the\s+|was\s+the\s+)?([a-z]+)", query.strip(), re.I)
        head_noun = fold(head_m.group(1)) if head_m else ""
        head_value_re = re.compile(VALUE_RE_FOR[head_noun], re.I) if head_noun in VALUE_RE_FOR else None
        long_terms = sorted({fold(t) for t in terms if len(t) >= 5 and not t.isdigit() and fold(t) != head_noun})
        if stem_terms:
            strategy.append("stems:" + ",".join(stem_terms))
        who_question = bool(_WHO_RE.match(query))
        alias_words: dict[str, set[str]] = {t: set() for t in terms}   # paraphrase coverage, scored below literal coverage
        if self.use_aliases:
            for key, phrases in expanded.items():
                words = {fold(w) for p in A.expansions_for_key(key, self.alias_table) for w in p.split() if len(w) > 2 and w not in STOPWORDS}
                for t in terms:
                    if any(t in p.split() for p in phrases):
                        alias_words[t] |= words - term_words[t]
        # Candidate narrowing: the feature sweep below is exact (substring, folded, regex) but O(rows × terms) — ~0.5 s
        # for the 33k-row G1R3A index, which with a loaded host pushed the plan stage over its budget (live K38
        # 2026-11-06, 1 513 ms of 1 500). Every feature needs *some* token of the question in the row's text, keys/
        # heading (``ctx``) or aliases (``al``); FTS finds those rows (prefix-matched, so inflections count) in
        # milliseconds. Rows of a named file are kept whole (the path-scope feature needs no token). Scoring itself
        # is unchanged; a FTS syntax error falls back to the full sweep.
        cand: set[int] | None = None
        if self.use_fts and self.narrow_candidates:
            toks = [t for t in dict.fromkeys([*literal_terms, *stem_terms, *(w for ws in alias_words.values() for w in ws), *expanded.keys()]) if t]
            parts = ['"' + t.replace('"', '""') + '"*' for t in toks]
            parts += ['"' + a.replace('"', '""') + '"' for a in dict.fromkeys([*quoted_raw, *ident_raw, *_CODE_RE.findall(query), *_NUM_RE.findall(query)]) if a.strip()]
            if parts:
                try:
                    with self._index.lock:
                        cand = {rid for (rid,) in self.db.execute("SELECT rowid FROM lines WHERE lines MATCH ?", (" OR ".join(parts),)).fetchall()}
                    cand |= set(bm25)
                    if explicit:
                        cand |= {r.rowid for fid in explicit for r in self._index.rows_by_file.get(fid, [])}
                    strategy.append(f"candidates:{len(cand)}/{len(in_scope)}")
                except sqlite3.OperationalError:
                    cand = None
        for rowid, r in in_scope.items():
            if cand is not None and rowid not in cand:
                continue
            if who_question and r.kind in ("key", "item") and _SCALAR_LEAF_RE.match(r.text):
                # a boolean or numeric leaf (`"labelled": true`) names nobody: for a who-question it cannot be the answer
                # and must not fill the excerpt slots (live K16: eight such leaves, the labeller sentence unranked)
                continue
            feats: dict[str, float] = {}
            base = bm25.get(rowid, 0.0)
            if base:
                feats["bm25"] = round(4.0 * base / bm_max, 3)   # scaled to [0, 4] so structure features stay comparable
            low = r.textn
            lowf = r.textf
            if self.use_structure:
                matched_keys = {k for k in r.keys if fold(k) in key_terms} if (r.keysf & key_terms) else set()
                if matched_keys:
                    feats["exact_key"] = round(3.0 * max(self._rarity(k) for k in matched_keys), 3)   # rare keys count more than a 6-row column
                if idents and any(i in low for i in idents):
                    feats["identifier"] = 2.5
                if r.heading and (literal_f & r.heading_words):
                    feats["heading"] = 1.0
            if self.use_aliases and r.key_aliases and (alias_terms & r.key_aliasesf):
                feats["alias_key"] = round(2.0 * max(self._rarity(k) for k in r.keys) if r.keys else 2.0, 3)
            if quoted and any(qv in low for qv in quoted):
                feats["quoted"] = 3.0
            if nums and any(re.search(rf"(?<![\w.]){re.escape(n)}(?![\w.])", r.text) for n in nums):
                feats["number"] = 1.0
            if (stem_terms or long_terms) and r.kind in ("paragraph", "item", "key"):
                # a prose line that *labels* its value with a word of the question's family — `Labeller: AGENT_…` for
                # "Who labelled the sealed set?" (live L12 G1R3D, 2026-11-06) — is the line that answers; the label is
                # not a parsed key (the parser kept the identifier in the value), so the stem meets it here
                lm = _LABEL_LINE_RE.match(r.text)
                if lm:
                    lab = fold(lm.group(1))
                    if any(st in lab for st in stem_terms) or any(t in lab for t in long_terms):   # `candidate_frozen_at:` says both words of "the frozen candidate" (live M13)
                        # a label whose value is not of the asked type is not the line: `frozen_utc: 2026-11-06T07:34:20Z`
                        # for "Which commit froze the blind set?" (live K17 after30/31 — the model read a commit off it)
                        if head_value_re is None or head_value_re.search(r.text[lm.end() - 1:]):
                            feats["label_stem"] = 3.0
            if r.scope_label and feats and not any(sw == f or (len(f) >= 5 and sw.startswith(f)) or (len(sw) >= 5 and f.startswith(sw)) for sw in r.scope_label for f in q_forms):
                # nested under a label the question does not name: the line's label is relative to its parent (`frozen in
                # commit` under `Sealed set`), so it is not the question's label line and its word coverage is discounted
                feats.pop("label_stem", None)
                feats["scoped_under"] = -3.0
            if not self.use_fts and any(fold(t) in lowf for t in search_terms):
                feats["substring"] = 1.0
            if terms:   # a line that covers more distinct question words beats a structural line matching one; a literal
                # question word counts 3.0, a curated-alias paraphrase 1.0 (the alias path stays open for "instances" ↔
                # "replicas", but can no longer let a ubiquitous key outrank the line that says the word)
                lit = sum(1 for t in terms if any(w in lowf for w in term_words[t]))
                via_alias = sum(1 for t in terms if alias_words[t] and not any(w in lowf for w in term_words[t]) and any(w in lowf for w in alias_words[t]))
                # a question word said by the line's *section heading* counts like a paraphrase: `| explicit-mutation
                # recall | 0.864 | 0.977 |` under `## 5. Burned re-score after the repair` covers "after the repair"
                # through its heading (live L08 G1R3D, 2026-11-06 — the row lost to source-code lines saying the same
                # three metric words); the heading feature alone is a flat 1.0 and cannot tell two from zero
                via_heading = 0
                if r.heading_words and lit < len(terms):
                    via_heading = sum(1 for t in terms if not any(w in lowf for w in term_words[t]) and not (alias_words[t] and any(w in lowf for w in alias_words[t]))
                                      and (term_words[t] & r.heading_words))
                if lit or via_alias or via_heading:
                    feats["term_coverage"] = round((3.0 * lit + 1.0 * via_alias + 1.0 * via_heading) / len(terms), 3)
                    feats["_lit"] = lit
                    feats["_cov"] = lit + via_alias + via_heading
            if explicit and r.file_id in explicit:
                feats["path_scope"] = 2.0 if feats else (0.5 if scope_files else 0.0)
            if why_question and feats:
                # "Why was the verdict HOLD?" (live K04 2026-11-06, lab and Granite): `"verdict": "HOLD"` dump lines and a
                # `+ verdict = "HOLD (…)" if …` patch line outranked `**Verdict: HOLD.** The one-time blind evaluation
                # failed two of the three pre-registered safety gates (…)`. A reason is words *beyond* the question's:
                # a line that only restates them explains nothing (−2.0); a line carrying a causal cue is the kind that
                # answers (+2.0). Both are read from the line, not from the question's subject.
                own = {w for w in _WORD_RE.findall(lowf) if len(w) > 2} - q_words - STOPWORDS
                if len(own) < 2:
                    # a restatement keeps its text match but no structure credit: being a key, heading or identifier
                    # does not make `"verdict": "HOLD"` a reason
                    for k in ("exact_key", "alias_key", "heading", "identifier", "label_stem"):
                        feats.pop(k, None)
                    feats["why_bare"] = -2.0
                elif _CAUSAL_RE.search(r.text):
                    feats["why_causal"] = 2.0
            score = sum(v for k, v in feats.items() if not k.startswith("_"))
            if score > 0 and r.seg_id:
                # a line no segment covers has no verifiable pointer: it can be neither quoted nor cited, so it is not a
                # hit (live M18 G1R3E, 2026-11-06: `source/tests/test_g1r3e_english.py:621` reached the node and failed it)
                hits.append(Hit(r.file_id, r.path, r.line, r.seg_id, r.text, round(score, 3), feats))
        best_lit = max((h.features.get("_lit", 0) for h in hits), default=0)
        best_cov = max((h.features.get("_cov", 0) for h in hits), default=0)
        if explicit and not scope_files and hits and best_cov:
            # soft focus ("the blind run" → the BLIND files) is a hint, not a scope: a line elsewhere that covers more of
            # the question's words than any focused line must not lose to the boost alone (live K11, 2026-11-06: the
            # focused `## 5. PUBLIC re-run after the safety increment` heading outranked `the six safety failures of the
            # blind run (E040, E086, …)` in 03_TESTS by 2.0 − 0.43). The boost scales with the line's share of the best
            # coverage seen (literal or alias — `Maintained by` answers "owner", oracle C064); a focused line that says as
            # much as the best keeps the full boost, and no focused line drops below half of it: the user pointed there.
            for h in hits:
                ps = h.features.get("path_scope")
                if ps and ps == 2.0:
                    share = max(0.5, h.features.get("_cov", 0) / best_cov)
                    if share < 1.0:
                        h.features["path_scope"] = round(2.0 * share, 3)
                        h.score = round(h.score - 2.0 + h.features["path_scope"], 3)
            strategy.append("focus_scaled_by_coverage")
        if best_lit >= 3:
            # the line(s) that say the most distinct words of the question are the most likely to answer it; bm25 shrinks
            # with line length, so a long sentence covering five question words (K11: `the six safety failures of the
            # blind run (E040, …)`, 5/7) scored below a short table header covering two. A bonus the structural features
            # cannot stack past keeps the best-covering lines ahead when they cover at least three words.
            for h in hits:
                if h.features.get("_lit", 0) == best_lit:
                    h.features["best_coverage"] = 1.5
                    h.score = round(h.score + 1.5, 3)
        for h in hits:
            h.features.pop("_lit", None)
            h.features.pop("_cov", None)
        hits.sort(key=lambda h: (-h.score, h.path, h.line))
        out: list[Hit] = []
        used = 0
        seen: set[tuple[str, int]] = set()
        # file diversity: unless the question names the file, a *bulky* file (more indexed lines than a few excerpt
        # windows) may fill at most half of the excerpt slots, so a 1500-leaf JSON dump cannot crowd the prose that
        # actually answers (live finding 2026-11-06: 7 of 8 excerpts for "Which gates failed in the blind run?" were
        # `BLIND/blind_v1.json` leaves; the markdown table line was 6th). Small files are never sampled: a 5-line
        # changelog must stay whole (oracle C063 regressed when the cap dropped the one line that answered).
        per_file_cap = max_hits if explicit else max(2, max_hits // 2)
        bulky_rows = 4 * max_hits
        per_file: dict[str, int] = {}
        # machine dumps as a *class*: the per-file cap holds one dump to half the slots, but a package that ships
        # thirteen result dumps (G1R3D, 2026-11-06: 280k of 294k indexed lines were JSON) fills every slot with them —
        # live L36 showed eight `"apply_change"` / `"change request"` leaves from six files and no prose at all. All
        # bulky dump files (json/csv/log …) together may fill at most half of the excerpt slots, and a dump leaf whose
        # text already appears in the excerpts (the same key repeated per case, per run) takes no further slot; prose
        # and markdown files are not dumps and keep the per-file rule only.
        dump_group_cap = max_hits if explicit else max(2, max_hits // 2)
        dump_used = 0
        dump_texts_seen: set[str] = set()
        # source code as a class: for a *prose* question (no identifier, quoted literal, code or number anchor) the
        # lines of program files together take at most a quarter of the slots — `f"expl.mut.recall {a['explicit_…']}"`
        # in four scoring scripts outranked the results table (live L08 G1R3D). A question that names an identifier,
        # a literal or a file is about code and keeps every slot open.
        prose_question = (not idents and not quoted and not nums and not scope_files) or (why_question and not scope_files)
        source_group_cap = max_hits if (explicit or not prose_question) else max(1, max_hits // 4)
        source_used = 0
        by_loc = {(rr.file_id, rr.line): rr for rr in in_scope.values()}
        # context companions (header for a row, heading for a line, body for a label) ride along in their own bounded
        # budget: they never displace a scored excerpt (oracle C064 regressed when five CSV rows pushed out the one
        # prose line that answered), and everything stays under max_chars
        extra_slots = max(3, max_hits * 3 // 4)   # 6 for the default 8
        # share the companion budget between the labels that will be selected, so the first table's rows cannot starve a
        # second table (live K11: `| mechanism | ids | assessment |` ranked 6th, its rows never shown). Every selected
        # table keeps its first TABLE_ROWS rows — a three-row gate table cut to two rows lost the very row asked about
        # (live K06: `negation inversions` was the third row of both tables) — and the headings share what is left.
        TABLE_ROWS = 3
        n_tables = sum(1 for h in hits[:max_hits] if by_loc[(h.file_id, h.line)].kind in ("table_header", "header"))
        n_heads = sum(1 for h in hits[:3] if by_loc[(h.file_id, h.line)].kind == "heading")
        extra_slots = max(extra_slots, TABLE_ROWS * n_tables + n_heads)
        per_heading = max(1, (extra_slots - TABLE_ROWS * n_tables) // max(1, n_heads))
        n_scored = n_extra = 0
        for h in hits:
            if n_scored >= max_hits or used + len(h.text) > max_chars:
                break
            if (h.file_id, h.line) in seen:
                continue
            if per_file.get(h.file_id, 0) >= per_file_cap and self._index.rows_per_file.get(h.file_id, 0) > bulky_rows:
                if "file_diversity_cap" not in strategy:
                    strategy.append("file_diversity_cap")
                continue
            if _SOURCE_EXT_RE.search(h.path) is not None and not (explicit and h.file_id in explicit):
                if source_used >= source_group_cap:
                    if "source_group_cap" not in strategy:
                        strategy.append("source_group_cap")
                    continue
                source_used += 1
            is_dump = _DUMP_EXT_RE.search(h.path) is not None and self._index.rows_per_file.get(h.file_id, 0) > bulky_rows
            if is_dump and not (explicit and h.file_id in explicit):
                tkey = " ".join(h.text.split())
                if tkey in dump_texts_seen:
                    if "dump_duplicate_line_skipped" not in strategy:
                        strategy.append("dump_duplicate_line_skipped")
                    continue
                if dump_used >= dump_group_cap:
                    if "dump_group_cap" not in strategy:
                        strategy.append("dump_group_cap")
                    continue
                dump_texts_seen.add(tkey)
                dump_used += 1
            per_file[h.file_id] = per_file.get(h.file_id, 0) + 1
            out.append(h)
            n_scored += 1
            seen.add((h.file_id, h.line))
            used += len(h.text)
            r = by_loc[(h.file_id, h.line)]
            companions: list[tuple[int, str, str]] = []
            if self.use_structure and r.header_line and (h.file_id, r.header_line) not in seen:
                companions.append((r.header_line, "header_for_row", "csv_header_companion"))
            elif self.use_structure and r.heading_line and n_scored <= 3 and (h.file_id, r.heading_line) not in seen and r.kind != "heading":
                companions.append((r.heading_line, "heading_for_line", "heading_companion"))   # dated/section heading is context for the top hits
            strong_heading = r.kind == "heading" and n_scored > 3 and float(h.features.get("term_coverage", 0.0)) >= 1.2
            if self.use_structure and r.kind in ("heading", "table_header", "header") and (n_scored <= 3 or r.kind != "heading" or strong_heading):
                # the hit is a *label* (section heading, table header row): the answer is in the lines it labels. Without
                # them the model quotes the label itself ("## 4. What must not happen", a header row) — live G1R3A
                # K25/K26/K31/K40, 2026-11-06. Body lines carrying a question word / identifier / number come first.
                # A table header matched at any rank brings its rows (the row cells rarely repeat the header's words:
                # live K11 — `| mechanism | ids | assessment |` was 6th and the `E040, E086, E118` row never shown);
                # section headings below rank 3 do not, their bodies are too broad. The companion budget caps it all.
                # a lower-ranked heading that itself carries two of the question's terms brings its first on-topic body
                # line (live K27 2026-11-06: `## 3. What may be consumed now (read-only, no decisions)` ranked 10th and
                # the answer — `may be logged in shadow …` — was the line under it)
                share = TABLE_ROWS if r.kind != "heading" else (1 if strong_heading else min(per_heading, 3 if n_scored <= 3 else 2))
                companions += self._label_body(r, literal_f, idents, nums, seen, max_lines=share)[:share]
            for ln, label, strat in companions:
                if n_extra >= extra_slots:
                    break
                hr = by_loc[(h.file_id, ln)]
                if used + len(hr.text) > max_chars:
                    break
                out.append(Hit(hr.file_id, hr.path, hr.line, hr.seg_id, hr.text, h.score, {label: 1.0}, companion_of=f"{h.path}:{h.line}"))
                seen.add((h.file_id, hr.line))
                used += len(hr.text)
                n_extra += 1
                if strat not in strategy:
                    strategy.append(strat)
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
