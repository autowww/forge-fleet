"""Typed D0 operators over tables and patches in the attachment map (Phase 2, 2026-11-06).

Markdown tables (``table_header`` + ``table_row`` segments) and CSV files (``header`` + ``row``) are read as tables:
columns, one label per row (the first cell), typed cells. Three zero-model operators answer from them, each guarded
the way ``typed_key_lookup`` is — every content word of the question must be explained by the table (label words,
column words, heading ancestry, file path) or be a request / comparison word, otherwise the node stays on the
verified-quote model path:

* ``typed_table_row`` — the question names a row (``explicit-mutation recall`` ↔ ``explicit_mutation_recall``): the
  row's cells, narrowed to the columns the question names (``threshold``, ``blind``). The same label in several tables
  lists every table's row with ``path:line`` and chooses none (live K09: the gate table and the report table both carry
  the recall; live K20: blind and public re-run are two columns of one CSV row).
* ``typed_table_extreme`` — "highest / lowest <column>": the row whose cell is the extreme of the named column, the
  column chosen by header-word overlap (``p95`` + ``projection`` → ``0.4.3 parse + projection p50 / p95``), a
  ``p50 / p95`` compound cell split by the header's own ``/`` sub-labels (live K40).
* ``typed_table_filter`` — "which gates failed": the rows of the table with a verdict column (``pass`` / ``status``)
  whose cell is a plain negative (or positive for "passed"); several verdict tables are narrowed by heading words
  (``blind``) and the operator abstains when the question does not single one out (live K06).
* ``typed_diff_rollup`` — "which files did the patch change": every ``diff_file`` segment of the ``.patch`` /
  ``.diff`` files with status and ±counts (live K33).

Nothing here interprets free text: labels and headers are matched word for word after folding, numbers are parsed
with one regex, and every answer carries the ``seg_id`` of the row it came from so the executor resolves it through
the map like any other span.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .attachment_map import AttachmentMap, Segment
from .lexicon import REQUEST_WORDS
from .retrieval import STOPWORDS, fold, norm

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_HYPHEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)+", re.UNICODE)
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_EXTREME_HIGH = {"highest", "largest", "biggest", "maximum", "max", "most", "slowest", "longest", "worst", "top"}
_EXTREME_LOW = {"lowest", "smallest", "minimum", "min", "least", "fastest", "shortest", "best", "quickest"}
# comparison / shape words that carry no table content and must not block the guard
_GENERIC = {"run", "runs", "value", "values", "number", "figure", "result", "results", "between", "versus", "vs", "compare",
            "compared", "comparison", "difference", "differ", "observed", "measured", "reported", "class", "which", "what",
            "had", "has", "have", "was", "were", "is", "are", "did", "does", "with", "and", "for", "the", "of", "in", "it",
            "its", "respectively", "both", "each", "per", "row", "table", "column", "entry", "across", "among", "all",
            "one", "ms", "latency", "time", "score", "rate", "level",
            "change", "changed", "changes", "move", "moved", "went", "go", "evolve", "evolved", "improve", "improved", "worsen", "worsened",
            "carry", "carries", "carried", "hold", "holds", "held", "give", "gives", "given", "show", "shows", "shown", "stated",
            "get", "gets", "got", "receive", "received", "receives"}
_PATCH_Q_RE = re.compile(r"\b(patch|diff|changeset|commit)\b", re.I)
_CHANGE_Q_RE = re.compile(r"\b(chang\w*|modif\w*|touch\w*|edit\w*|affect\w*|differ\w*)\b", re.I)
_FILES_Q_RE = re.compile(r"\b(files?|sources?|modules?|paths?)\b", re.I)
_SHA_RE = re.compile(r"(?<![\w/.-])([0-9a-f]{7,40})(?![\w/-])")
_LOG_LINE_RE = re.compile(r"^([0-9a-f]{7,40})[ \t]+(\S.*)$")


def _shas_in(text: str) -> list[str]:
    """Abbreviated or full git hashes written in the text: hex of 7–40 chars that carries both a digit and a letter (so
    a plain number such as 2026110 or a word such as `decaded` is not one), folded, in order of appearance."""
    out = []
    for m in _SHA_RE.finditer(text.casefold()):
        h = m.group(1)
        if re.search(r"\d", h) and re.search(r"[a-f]", h) and h not in out:
            out.append(h)
    return out


@dataclass
class Row:
    seg: Segment
    cells: dict[str, str]
    label: str
    label_words: frozenset[str]


@dataclass
class Table:
    file_id: str
    path: str
    columns: list[str]
    heading: list[str]
    rows: list[Row] = field(default_factory=list)

    @property
    def column_words(self) -> dict[str, frozenset[str]]:
        return {c: _words(c) for c in self.columns}


def _words(s: str) -> frozenset[str]:
    """Folded word parts plus the collapsed form of every hyphenated word (``re-run`` → ``re``, ``run``, ``rerun``), so a
    markdown ``public re-run`` column and a CSV ``public_rerun`` column explain the same question."""
    t = norm(str(s))
    out = {fold(w) for w in _WORD_RE.findall(t) if w}
    out |= {fold(h.replace("-", "")) for h in _HYPHEN_RE.findall(t)}
    return frozenset(out)


def _content_words(query: str) -> list[str]:
    """Question words that must be explained: no stop / request words, no fragments shorter than three characters (the
    ``re`` of ``re-run``) unless numeric; hyphenated words contribute their collapsed form as well."""
    t = norm(query)
    words = [fold(w) for w in _WORD_RE.findall(t) if w and fold(w) not in STOPWORDS and fold(w) not in REQUEST_WORDS and (len(w) > 2 or w.isdigit())]
    words += [fold(h.replace("-", "")) for h in _HYPHEN_RE.findall(t)]
    return list(dict.fromkeys(words))


def tables_of(amap: AttachmentMap) -> list[Table]:
    """Tables from the map: markdown rows are grouped under the nearest ``table_header`` above them (a new header starts a
    new table even when the columns repeat), CSV rows under the file's ``header``."""
    out: list[Table] = []
    files = {f.file_id: f for f in amap.files}
    for fid, f in files.items():
        if f.status != "INCLUDED":
            continue
        current: Table | None = None
        for s in amap.segments_for(fid):
            if s.kind in ("table_header", "header"):
                cols = [str(c) for c in s.context.get("columns", [])]
                current = Table(fid, f.path, cols, [norm(str(h)) for h in s.context.get("heading_ancestry", [])])
                out.append(current)
            elif s.kind in ("table_row", "row"):
                cells = {str(k): str(v) for k, v in (s.context.get("cells") or {}).items()}
                if current is None or list(cells) != current.columns:
                    current = Table(fid, f.path, list(cells), [norm(str(h)) for h in s.context.get("heading_ancestry", [])])
                    out.append(current)
                label = next((v for v in cells.values() if v.strip()), "").strip().strip("*`").strip()
                current.rows.append(Row(s, cells, label, frozenset(fold(w) for w in _WORD_RE.findall(norm(label)) if w)))   # parts only: `a-b` = `a_b`
    return [t for t in out if t.rows]


def _explained(t: Table, extra: set[str]) -> set[str]:
    ex = set(extra) | _GENERIC
    for c in t.columns:
        ex |= _words(c)
    for h in t.heading:
        ex |= _words(h)
    ex |= _words(t.path.replace("/", " ").replace(".", " "))
    return ex


def _sing(w: str) -> str:
    """``overgrants`` ↔ ``over-grant``, ``inversions`` ↔ ``inversion``: a label's plural meets the question's singular
    (live L04/L06 G1R3D, 2026-11-06); three-letter words and digits stay as they are."""
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _hyphen_parts(query: str, explained: set[str]) -> set[str]:
    """The parts of a hyphenated question word whose collapsed form the table explains: ``over-grant`` is explained by
    the label ``policy_overgrants`` as a whole, so its parts ``over`` and ``grant`` are not leftovers."""
    out: set[str] = set()
    ex_s = {_sing(e) for e in explained}
    for h in _HYPHEN_RE.findall(norm(query)):
        if _sing(fold(h.replace("-", ""))) in ex_s:
            out |= {fold(p) for p in h.split("-")}
    return out


_WHY_ROW_RE = re.compile(r"^\s*(?:why|for what reason|what (?:is|was) the reason)\b", re.I)
_COUNT_COLS = frozenset({"n", "count", "total", "cases", "size", "items", "rows", "samples"})
_COUNTED_NOUNS = frozenset({"cases", "case", "items", "item", "entries", "entry", "records", "record", "rows", "row", "samples", "sample", "questions", "question", "sentences", "sentence", "examples", "example"})
_HOW_MANY_RE = re.compile(r"^\s*how many\b|\bnumber of\b|\bhow much\b", re.I)
_PERCENTILE_RE = re.compile(r"^p\d{1,2}$")
_METRIC_DESCRIPTORS = frozenset({"latency", "request", "requests", "response", "time", "duration", "wall", "elapsed"})   # what a p95/ms label measures


def _inflected_hit(col: str, qset: set[str]) -> bool:
    cw = _words(col) - STOPWORDS
    return any(w == e or (len(w) > 4 and len(e) > 4 and (w.startswith(e[:5]) or e.startswith(w[:5]))) or (len(w) > 3 and w.rstrip("s") == e.rstrip("s"))
               or (len(e) >= 4 and w.startswith(e) and len(w) - len(e) <= 3)   # `flagged` ~ `flag(s)`
               for w in qset for e in cw)


def _guard(words: list[str], explained: set[str]) -> list[str]:
    """Question words the table cannot account for (prefix match of ≥5 chars tolerates inflection: ``labelled``/``label``)."""
    return [w for w in words if w not in explained and not w.isdigit()
            and not any(((w.startswith(e[:5]) or e.startswith(w[:5])) and len(e) > 4 and len(w) > 4) or (len(w) > 3 and w.rstrip("s") == e.rstrip("s"))
                        or (len(e) >= 4 and w.startswith(e) and len(w) - len(e) <= 3)   # `flagged` ~ `flag(s)`, `passed` ~ `pass` (live M22 G1R3E)
                        for e in explained)]   # `test` ~ `tests` (oracle C081: "rows in the test results" over tests/results.csv)


def _numbers(cell: str) -> list[float]:
    return [float(m.replace(",", ".")) for m in _NUM_RE.findall(cell)]


# --- row lookup --------------------------------------------------------------------------------------------------------------
_CODE_RE = re.compile(r"(?<![\w-])([A-Z]{1,3}\d{1,4})(?![\w-])")
_WH_OTHER_RE = re.compile(r"^\s*(who|whom|whose|why|when|where)\b", re.I)


def _keyed_row(amap: AttachmentMap, query: str, words: list[str]) -> dict[str, Any] | None:
    """``What is the acceptance criterion for item B1 …`` (K25): an identifier-style label (``B1``, ``E040``) written in
    the question that is the label of exactly one table row in the package, plus at least one named column of that
    table, is a key lookup — the code pins the row, the column word pins the cell. The word guard is relaxed to the
    words that could ask for another *kind* of data: a leftover word that is a column header word of another table
    aborts (``… for item B1 in the latency table``); a common noun that merely occurs in another table's row label
    (``increment`` in ``Post-blind safety increment``) cannot outrank the identifier and is let through."""
    if _WH_OTHER_RE.match(query):
        return None
    codes = {c.casefold() for c in _CODE_RE.findall(query)}
    if len(codes) != 1:
        return None
    code = next(iter(codes))
    ts = tables_of(amap)
    hits = [(t, r) for t in ts for r in t.rows if r.label.casefold() == code]
    if len(hits) != 1:
        return None
    t, r = hits[0]
    qset = set(words)
    # ``item B1`` / ``case E040``: the word in front of the code names the row's kind, not a column to read
    m = re.search(r"([^\W\d_]+)\s+" + re.escape(code), query, re.I)
    determiner = {fold(m.group(1))} if m else set()
    cols = [c for c in t.columns[1:] if (_words(c) - STOPWORDS) & qset]
    narrowed = [c for c in cols if (_words(c) - STOPWORDS) & (qset - determiner)]
    cols = narrowed or cols
    if not cols:
        return None
    other_words: set[str] = set()
    for o in ts:
        if o is not t:
            for c in o.columns:
                other_words |= _words(c)
    other_words -= STOPWORDS | _GENERIC | {code} | _explained(t, set())
    leftover = [w for w in _guard(words, _explained(t, {code}) | r.label_words) if w in other_words]
    if leftover:
        return None
    entry = {"path": t.path, "line": r.seg.start_line, "seg_id": r.seg.seg_id, "label": r.label,
             "cells": [{"column": c, "value": r.cells.get(c, "").strip()} for c in cols if r.cells.get(c, "").strip()], "columns_named": True}
    if not entry["cells"]:
        return None
    return {"method": "typed_table_row", "label": r.label, "entries": [entry], "note": "", "keyed": True}


def typed_table_row(amap: AttachmentMap, query: str, *, continuation_of: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """``continuation_of`` — the row result of the previous goal in the same sentence; the query then is that row's label
    plus the elliptical goal's words, and the result is marked so the renderer says which row it continues."""
    words = _content_words(query)
    if len(words) < 2:
        return None
    keyed = _keyed_row(amap, query, words) if continuation_of is None else None
    if keyed:
        return keyed
    qset = set(words)
    # the label is matched against every question word, short ones included: `op pass` needs the `op` that
    # _content_words drops (live M24 G1R3E); a one-word label must be long or carry a digit (`J165`, `H126` — ids are
    # specific; `n` or `ms` is not)
    qall = {fold(w) for w in _WORD_RE.findall(norm(query)) if len(w) > 1} | qset
    matches: list[tuple[Table, Row]] = []
    for t in tables_of(amap):
        for r in t.rows:
            lw = r.label_words - STOPWORDS - _UNIT_WORDS   # `short_p95_ms` answers "short-request p95 latency" (K13)
            if len(lw) < 1 or (len(lw) == 1 and len(next(iter(lw))) < 6 and not any(ch.isdigit() for ch in next(iter(lw)))):
                continue
            if {_sing(w) for w in lw} <= {_sing(w) for w in qall}:
                matches.append((t, r))
    if not matches:
        return None
    # the longest label match wins (``explicit mutation recall`` over ``recall``); ties across tables are all kept
    best_len = max(len(r.label_words - STOPWORDS - _UNIT_WORDS) for _, r in matches)
    longest = [(t, r) for t, r in matches if len(r.label_words - STOPWORDS - _UNIT_WORDS) == best_len]
    # … unless the longest-labelled tables alone cannot explain the question: "short-request p95 latency and its threshold"
    # matches `Short-request P95 latency` in a review table with no threshold column and `short_p95_ms` in the gate tables
    # that have one — then every matching table is kept and listed (K13 2026-11-06)
    longest_explained = set().union(*(r.label_words for _, r in longest)) | set().union(*(_explained(t, set()) for t, _r in longest))
    if _guard(words, longest_explained | _hyphen_parts(query, longest_explained)):
        longest = matches
    matches = longest
    label_words = set().union(*(r.label_words for _, r in matches))
    # run qualifiers: a question word that is neither the label nor a column — "… on the *blind* run" — and that some
    # matched tables carry affirmatively in their heading or path while others do not, keeps only those tables (live
    # L04 G1R3D, 2026-11-06: eleven gate tables, one per run, all said `policy_overgrants`; the question said blind)
    label_s = {_sing(w) for w in label_words}
    qualifier_notes: list[str] = []
    for w in words:
        if _sing(w) in label_s or w in _GENERIC or w in _hyphen_parts(query, label_words) or w.isdigit():
            continue
        carrying = [(t, r) for t, r in matches if _affirmations(t, w) or any(w in _words(c) for c in t.columns)]
        if carrying and len(carrying) < len(matches):
            matches = carrying
            qualifier_notes.append(f"only the tables whose heading, path or columns say `{w}`")
    depth_note = ""
    if len(matches) > 3:
        shallowest = min(t.path.count("/") for t, _r in matches)
        top_level = [(t, r) for t, r in matches if t.path.count("/") == shallowest]
        if top_level and len(top_level) < len(matches):
            depth_note = f"{len(matches) - len(top_level)} further table(s) with this row sit deeper in the package and are not listed"
            matches = top_level
    # columns the question names (any header word besides the label column); none named → every cell
    picked_cols: dict[int, list[str]] = {}
    for i, (t, _r) in enumerate(matches):
        cols = [c for c in t.columns[1:] if (_words(c) - STOPWORDS) & qset]
        if not cols or len(cols) < len([c for c in t.columns[1:] if _inflected_hit(c, qset)]):
            # `repaired` names the column `After repair` as surely as `candidate` names `Frozen candidate`: inflection counts
            # the same way the guard counts it, so a question that names two columns shows both (live L16 G1R3D, 2026-11-06)
            cols = [c for c in t.columns[1:] if _inflected_hit(c, qset)]
        picked_cols[i] = cols
    explained = set(label_words)
    for t, _r in matches:
        explained |= _explained(t, set())
    explained |= _hyphen_parts(query, explained)
    if any(_PERCENTILE_RE.match(w) or w in ("ms", "sec", "secs", "seconds") for w in label_words | set(words)):
        explained |= _METRIC_DESCRIPTORS   # `short_p95_ms` *is* the short-request latency: the descriptors name what it measures (live L09 G1R3D)
    # "How many cases are in the pronoun_reference slice?" (live L23 G1R3D): a how-many question over a row is answered by
    # the row's count column (`n`, `count`, `total`, `cases`, `size`); the counted noun is what that column counts
    count_cols = {i: [c for c in t.columns[1:] if (_words(c) & _COUNT_COLS)] for i, (t, _r) in enumerate(matches)}
    how_many = bool(_HOW_MANY_RE.search(query)) and any(count_cols.values())
    if how_many:
        explained |= _COUNTED_NOUNS
    leftover = _guard(words, explained)
    if leftover:
        return None
    entries = []
    # "the p95 latency *and* its threshold": a coordinated question asks for the metric's own cells as well as the named
    # column — the named column(s) come first, the rest of the row follows (K13 2026-11-06)
    coordinated = bool(re.search(r"\b(and|with|plus|along with|as well as)\b", query, re.I))
    why_row = bool(_WHY_ROW_RE.match(query))   # "Why was J068 flagged?" — the whole adjudication row is the answer, not one cell (live M22 G1R3E)
    for i, (t, r) in enumerate(matches):
        if why_row:
            picked_cols[i] = []
        if how_many and not picked_cols[i] and count_cols[i]:
            picked_cols[i] = count_cols[i][:1]
        cols = picked_cols[i] or [c for c in t.columns[1:]]
        if len(picked_cols[i]) == 1 and coordinated:   # two named columns: the "and" joins them, not the metric to a column
            cols = picked_cols[i] + [c for c in t.columns[1:] if c not in picked_cols[i]]
        entries.append({"path": t.path, "line": r.seg.start_line, "seg_id": r.seg.seg_id, "label": r.label,
                        "cells": [{"column": c, "value": r.cells.get(c, "").strip()} for c in cols if r.cells.get(c, "").strip()],
                        "columns_named": bool(picked_cols[i])})
    if any(e["columns_named"] for e in entries):
        entries = [e for e in entries if e["columns_named"]]   # tables without the named column do not answer the question
    entries.sort(key=lambda e: (e["path"], e["line"]))
    note = "" if len(entries) == 1 else f"the row appears in {len(entries)} tables; all shown, none chosen"
    for qn in qualifier_notes:
        note = (note + "; " if note else "") + qn
    if depth_note:
        note = (note + "; " if note else "") + depth_note
    if continuation_of is not None:
        if not any(e["columns_named"] for e in entries):
            return None   # the elliptical goal names no column of the row's tables: nothing deterministic to read
        note = (note + "; " if note else "") + f"read from the same row as the previous part of the question (`{continuation_of['label']}`)"
    return {"method": "typed_table_row", "label": entries[0]["label"], "entries": entries, "note": note}


# --- extreme over a column ---------------------------------------------------------------------------------------------------
def typed_table_extreme(amap: AttachmentMap, query: str) -> dict[str, Any] | None:
    words = _content_words(query)
    qset = set(words)
    qlow = norm(query)
    # an extreme word must stand alone — ``max_8000`` is a row label, not a request for the maximum
    high = {w for w in _EXTREME_HIGH if re.search(rf"(?<![\w_-]){w}(?![\w_-])", qlow)}
    low = {w for w in _EXTREME_LOW if re.search(rf"(?<![\w_-]){w}(?![\w_-])", qlow)}
    if bool(high) == bool(low):
        return None
    want_max = bool(high)
    cands: list[tuple[int, Table, str, int | None]] = []   # (overlap, table, column, sub-index)
    for t in tables_of(amap):
        for c in t.columns[1:]:
            cw = _words(c) - STOPWORDS
            overlap = len(cw & qset)
            if overlap == 0:
                continue
            sub = None
            if "/" in c:
                # ``… p50 / p95``: the sub-labels are the words that touch the slash, not the whole header halves
                parts = [p.split() for p in c.split("/")]
                labels = [fold(p[-1]) if p else "" for p in parts[:-1]] + [fold(parts[-1][0]) if parts[-1] else ""]
                hits = [i for i, lb in enumerate(labels) if lb and lb in qset]
                if len(hits) == 1:
                    sub = hits[0]
                else:
                    continue   # compound column and the question does not say which half
            cands.append((overlap, t, c, sub))
    if not cands:
        return None
    top = max(o for o, *_ in cands)
    best = [x for x in cands if x[0] == top]
    if len(best) > 1:
        # "Which *slice* had the lowest op pass?": the table whose label column the question names (`slice`) beats the
        # `Pass` columns of the gate tables (live L24 G1R3D, 2026-11-06); the same table repeated per run deeper in the
        # package (public/*_REPORT.md) yields to the top-level copy
        named = [x for x in best if (_words(x[1].columns[0]) - STOPWORDS) & qset]
        if named:
            best = named
        if len(best) > 1:
            shallowest = min(x[1].path.count("/") for x in best)
            best = [x for x in best if x[1].path.count("/") == shallowest]
    if len(best) > 1:
        return None   # two columns explain the question equally well: not a deterministic choice
    _o, t, col, sub = best[0]
    explained = _explained(t, set(_EXTREME_HIGH | _EXTREME_LOW))
    for r in t.rows:
        explained |= r.label_words
    if _guard(words, explained):
        return None
    scored: list[tuple[float, Row, str]] = []
    for r in t.rows:
        cell = r.cells.get(col, "")
        nums = _numbers(cell)
        if not nums:
            continue
        if sub is not None:
            if len(nums) <= sub:
                continue
            val = nums[sub]
        elif len(nums) == 1:
            val = nums[0]
        else:
            return None   # several numbers in the cell and no sub-label to pick by
        scored.append((val, r, cell))
    if len(scored) < 2:
        return None
    val, r, cell = (max if want_max else min)(scored, key=lambda x: x[0])
    ties = [x for x in scored if x[0] == val]
    if len(ties) > 1:
        return None
    return {"method": "typed_table_extreme", "extreme": "highest" if want_max else "lowest", "column": col, "sub": None if sub is None else col.split("/")[sub].strip(),
            "label": r.label, "value": val, "cell": cell.strip(), "path": t.path, "line": r.seg.start_line, "seg_id": r.seg.seg_id,
            "rows_considered": len(scored), "others": [{"label": x[1].label, "value": x[0], "line": x[1].seg.start_line} for x in sorted(scored, key=lambda x: -x[0] if want_max else x[0])[1:4]]}


_UNIT_WORDS = frozenset({"ms", "sec", "secs", "s", "pct", "percent", "count", "n", "num", "total"})   # unit / measure suffixes of row labels

_FILTER_NEG = {"failed", "fail", "fails", "failing", "missed", "unmet", "red"}
_FILTER_POS = {"passed", "pass", "passes", "passing", "met", "green"}
_VERDICT_COLS = {"pass", "passed", "status", "result", "verdict", "ok", "met", "outcome"}
_NEG_CELLS = {"no", "fail", "failed", "false", "✗", "❌", "x", "miss", "missed", "unmet", "red", "n"}
_POS_CELLS = {"yes", "pass", "passed", "true", "✓", "✔", "✅", "ok", "met", "green", "y"}
_PLURAL_WHICH_RE = re.compile(r"^\s*(which|what|list|name|how many)\b", re.I)
_NEGATED_FILTER_RE = re.compile(r"\b(not|n't|never|no|without|didn.t|don.t|doesn.t)\b[^.?!]{0,24}?\b(" + "|".join(sorted(_FILTER_NEG | _FILTER_POS)) + r")\b", re.I)


_DENIAL_RE = r"(?<![\w])(not|non|no|never|without|post|pre|after|before|ex)[ _-](a |an |the )?{w}(?![\w])"


def _affirmations(t: Table, w: str) -> int:
    """How often a heading of the table or its path carries ``w`` *affirmatively*: "not a blind result" and
    ``POST_BLIND_PUBLIC/`` name blind only to deny it, so they count zero."""
    n = 0
    # a path quoted inside a heading (`gates (artifacts/…/blind/PROTOCOL.md §5)`) is a reference, not what the table is
    # about: every burned report of G1R3D cited the blind protocol that way (live L04, 2026-11-06)
    heads = [" ".join(tok for tok in h.split() if "/" not in tok) for h in t.heading]
    for text in [*heads, t.path.replace("/", " ").replace(".", " ")]:
        low = norm(text).replace("_", " ").replace("-", " ")   # `g1r3a_gates` names g1r3a and gates (K08)
        n += max(0, len(re.findall(rf"(?<![\w]){re.escape(w)}(?![\w])", low)) - len(re.findall(_DENIAL_RE.format(w=re.escape(w)), low)))
    return n


_PRED_ZERO_RE = re.compile(r"\b(?:no|zero|without|none|clean(?:\s+on)?|free of)\b", re.I)
_PRED_NONZERO_RE = re.compile(r"\b(?:any|at least one|some|nonzero|non-zero|one or more)\b", re.I)
_SUBJECT_RE = re.compile(r"^\s*(?:which|what|list|name)\s+(?:of\s+the\s+)?([a-z][a-z_\-]+)", re.I)
_PRED_WORDS = frozenset({"no", "zero", "without", "none", "clean", "free", "any", "least", "some", "nonzero", "non", "more", "every", "both", "all"})


def typed_table_predicate(amap: AttachmentMap, query: str) -> dict[str, Any] | None:
    """"Which slices had no over-grants and no cross-effects?" — the rows whose cells are zero (or non-zero) in **every**
    column the question names; columns are matched by header words with inflection, the predicate is read once for the
    question ("no / zero / without / clean" or "any / at least one"), and every other content word must be explained by
    the table. A column the question does not name is not read, so "clean on every safety column" with no column named
    `safety` yields nothing rather than a guess (live L25 G1R3D, kept as a miss). Output has the ``typed_table_filter``
    shape so the renderer lists each row with the named cells and ``path:line``."""
    if not _PLURAL_WHICH_RE.search(query):
        return None
    zero, nonzero = bool(_PRED_ZERO_RE.search(query)), bool(_PRED_NONZERO_RE.search(query))
    if zero == nonzero:
        return None
    words = _content_words(query)
    qset = {w for w in words if w not in _PRED_WORDS}
    sm = _SUBJECT_RE.match(norm(query))
    subject = fold(sm.group(1)) if sm else ""
    out = []
    for t in tables_of(amap):
        # the rows asked for are the table's rows: "which slices" reads a table whose first column is `slice`, not the
        # per-case CSV that merely has a `slice` column (live blind_v1.csv, 180 rows)
        if not subject or not _inflected_hit(t.columns[0], {subject}):
            continue
        named = [c for c in t.columns[1:] if _inflected_hit(c, qset - {subject}) or (_hyphen_parts(query, _words(c)) & qset)]
        numeric = [c for c in named if sum(1 for r in t.rows if _numbers(r.cells.get(c, ""))) >= max(1, len(t.rows) // 2)]
        if not numeric:
            continue
        explained = _explained(t, set(_PRED_WORDS)) | set().union(*(_words(c) for c in numeric)) | _words(t.columns[0])
        explained |= _hyphen_parts(query, explained)
        if _guard([w for w in words if w not in _PRED_WORDS], explained):
            continue
        entries = []
        for r in t.rows:
            vals = [(c, _numbers(r.cells.get(c, ""))) for c in numeric]
            if any(not v for _c, v in vals):
                continue
            ok = all(v[0] == 0 for _c, v in vals) if zero else all(v[0] != 0 for _c, v in vals)
            if ok:
                entries.append({"label": r.label, "line": r.seg.start_line, "seg_id": r.seg.seg_id, "cell": "; ".join(f"{c} {r.cells.get(c, '').strip()}" for c in numeric),
                                "cells": [{"column": c, "value": r.cells.get(c, "").strip()} for c in t.columns[1:] if c not in numeric][:4]})
        out.append({"path": t.path, "heading": " / ".join(t.heading[-1:]), "column": ", ".join(numeric), "rows_considered": len(t.rows), "entries": entries})
    if not out:
        return None
    out.sort(key=lambda tb: (tb["path"].count("/"), tb["path"]))
    note = "" if len(out) == 1 else f"{len(out)} tables name every column asked; the {min(3, len(out))} shallowest are listed, none chosen"
    return {"method": "typed_table_filter", "op": "typed_table_predicate", "want": ("zero" if zero else "non-zero"), "tables": out[:3], "note": note}


def typed_table_filter(amap: AttachmentMap, query: str) -> dict[str, Any] | None:
    """"Which gates failed (in the blind run)?" — the rows of the table(s) with a verdict column (``pass`` / ``status`` /
    ``result``) whose cell is a plain negative (``no``, ``fail``, ``✗``) or, for "passed", a plain positive. Tables are
    chosen by the verdict column and narrowed by the question words their headings / paths carry affirmatively ("not a
    blind result" does not count as blind); when several tables tie, each is listed with its own ``path:line`` rows, as
    ``typed_table_row`` does, and none is chosen. Every other content word must be explained by the table."""
    words = _content_words(query)
    if not _PLURAL_WHICH_RE.search(query):
        return None
    neg = {w for w in words if w in _FILTER_NEG}
    pos = {w for w in words if w in _FILTER_POS}
    if bool(neg) == bool(pos):
        return None
    complement = bool(_NEGATED_FILTER_RE.search(norm(query)))
    if complement:
        neg, pos = pos, neg   # "which tests did not pass" asks for the failures (oracle C025)
    want = _NEG_CELLS if neg else _POS_CELLS
    # a negated question asks for the complement: "did not pass" covers `skipped` and `n/a` as well as `failed`
    # (oracle C025: test_export,skipped was left out of "which tests did not pass"), while "which tests failed" stays exact
    avoid = (_POS_CELLS if neg else _NEG_CELLS) if complement else None
    rest = [w for w in words if w not in _FILTER_NEG | _FILTER_POS]
    cands: list[tuple[Table, str]] = []
    for t in tables_of(amap):
        vcols = [c for c in t.columns[1:] if _words(c) & _VERDICT_COLS and any(fold(r.cells.get(c, "").strip().strip("*`_ ")) in (_NEG_CELLS | _POS_CELLS) for r in t.rows)]
        if len(vcols) > 1:
            # several verdict columns (`blind_pass`, `public_pass` — live K08 2026-11-06): the one whose header words the
            # question names; none named or several → the table cannot say which run the question means
            named = [c for c in vcols if (_words(c) - _VERDICT_COLS - STOPWORDS) & set(rest)]
            if len(named) != 1:
                continue
            vcols = named
        if vcols:
            cands.append((t, vcols[0]))
    if not cands:
        return None
    qlow = norm(query)
    named = [(t, c) for t, c in cands if t.path.casefold() in qlow or t.path.rsplit("/", 1)[-1].casefold() in qlow]
    if named:
        cands = named   # "… according to g1r3a_gates.csv": the table the question names is the one asked about (K08)
    # distinct question words a table carries affirmatively, then how often: the blind summary and the blind report both
    # say "blind" twice over, the public re-run names it once and only to deny it (live K06)
    scored = [((sum(1 for w in rest if _affirmations(t, w) or w in _words(c)), sum(_affirmations(t, w) for w in rest)), t, c) for t, c in cands]
    # a question word that is the *value* of a categorical column in some rows and not all (`safety` in `Kind`) is a row
    # filter — "Which safety gates failed?" keeps the safety rows (live L05 G1R3D, 2026-11-06); it also explains the word
    def _categories(t: Table, col: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for c in t.columns[1:]:
            if c == col:
                continue
            vals = [fold(r.cells.get(c, "").strip().strip("*`_ ")) for r in t.rows]
            for w in rest:
                n = sum(1 for v in vals if v == w)
                if 0 < n < len(vals):
                    out[w] = c
        return out
    scored = [((sc[0] + sum(1 for w in rest if w in _categories(t, c) and not (_affirmations(t, w) or w in _words(c))), sc[1]), t, c) for sc, t, c in scored]
    top = max(sc for sc, *_ in scored)
    if top[0] == 0 and len(cands) > 1:
        return None   # nothing in the question says which verdict table
    best = [(t, c) for sc, t, c in scored if sc == top]
    depth_note = ""
    if len(best) > 3:
        # a package that ships the same gate table for every run (blind, burned, baseline — live L05 G1R3D: nine tables):
        # the ones in the shallowest folder are the package's own summary; the deeper copies are its supporting material
        shallowest = min(t.path.count("/") for t, _c in best)
        top_level = [(t, c) for t, c in best if t.path.count("/") == shallowest]
        if len(top_level) > 3:
            # the same tier still holds several copies (live M09 G1R3E: blind_v1_REPORT, blind_v1_BURNED_postfix_REPORT and
            # four public/burned_*_regression(_postfix)_REPORT tables): the ones whose path carries qualifiers the question
            # does not name — burned, postfix, regression, g1r3c — are qualified copies; the plainest path is the run the
            # unqualified question means. Ties stay unresolved.
            qwords = set(words) | set(_WORD_RE.findall(norm(query)))
            toks = {t.path: set(re.findall(r"[a-z0-9]+", t.path.casefold())) - qwords - STOPWORDS for t, _c in top_level}
            common = set.intersection(*toks.values())
            extra_ct = {pth: len(tk - common) for pth, tk in toks.items()}
            fewest = min(extra_ct.values())
            plain = [(t, c) for t, c in top_level if extra_ct[t.path] == fewest]
            if len(plain) > 3 or (len(plain) == len(top_level)):
                return None
            plain_toks = set().union(*(toks[t.path] for t, _c in plain))
            quals = sorted(set().union(*(toks[t.path] - common - plain_toks for t, _c in top_level if extra_ct[t.path] != fewest)))
            depth_note = (f"{len(top_level) - len(plain)} further table(s) at the same depth carry qualifiers in their path the question does not name "
                          f"({', '.join(quals)}) and are not listed")
            top_level = plain
        else:
            depth_note = f"{len(best) - len(top_level)} further table(s) with the same verdict column sit deeper in the package and are not listed"
        best = top_level
    extra = set(_FILTER_NEG | _FILTER_POS | {"gates", "gate", "rows", "checks", "criteria", "items"})
    out_tables = []
    for t, col in best:
        cats = _categories(t, col)
        if _guard(words, _explained(t, extra | _words(col) | set(cats))):
            return None
        def _hit(r: Row) -> bool:
            cell = fold(r.cells.get(col, "").strip().strip("*`_ "))
            if any(fold(r.cells.get(cc, "").strip().strip("*`_ ")) != w for w, cc in cats.items()):
                return False
            return (cell not in avoid and bool(cell)) if avoid is not None else cell in want
        rows = [r for r in t.rows if _hit(r)]
        out_tables.append({"path": t.path, "column": col, "heading": t.heading[-1] if t.heading else "", "rows_considered": len(t.rows),
                           "entries": [{"label": r.label, "cell": r.cells.get(col, "").strip(), "line": r.seg.start_line, "seg_id": r.seg.seg_id,
                                        "cells": [{"column": c, "value": v.strip()} for c, v in r.cells.items() if c != col and v.strip() and v.strip() != r.label][:3]} for r in rows]})
    if not any(tb["entries"] for tb in out_tables):
        return None   # "none" would be a claim without a span to carry it; the verified-quote path answers that
    note = "" if len(out_tables) == 1 else f"{len(out_tables)} tables carry a verdict column the question fits equally well; each is listed and none is chosen"
    if depth_note:
        note = (note + "; " if note else "") + depth_note
    return {"method": "typed_table_filter", "want": "negative" if neg else "positive", "tables": out_tables, "note": note}


# --- patch rollup --------------------------------------------------------------------------------------------------------------
def typed_diff_rollup(amap: AttachmentMap, query: str) -> dict[str, Any] | None:
    if not (_PATCH_Q_RE.search(query) and (_CHANGE_Q_RE.search(query) or _FILES_Q_RE.search(query))):
        return None
    patches = [f for f in amap.files if f.status == "INCLUDED" and f.path.lower().rsplit(".", 1)[-1] in ("patch", "diff")]
    if not patches:
        return None
    qlow = query.casefold()
    qtoks = {t for t in re.findall(r"[a-z0-9]+(?:[_-][a-z0-9]+)*", qlow) if len(t) >= 4 and t not in _GENERIC and t not in STOPWORDS and t not in ("patch", "diff", "files", "source", "sources")}
    named = [f for f in patches if f.path.casefold() in qlow or f.path.rsplit("/", 1)[-1].casefold() in qlow
             or (qtoks & set(re.split(r"[/_\-.]+", f.path.casefold())))]
    chosen = named or patches
    if len(chosen) > 1 and not named:
        return None   # several patches and the question names none: the model path shows the excerpts instead
    # every commit hash the question names must be part of a chosen patch's name — "between 766cb08 and 623c957" is a
    # commit-range question (K22), not a request for the file list of a patch that happens to end at 623c957
    chosen_text = " ".join(f.path.casefold() for f in chosen)
    if any(sha not in chosen_text for sha in _shas_in(query)):
        return None
    files_out = []
    for f in chosen:
        for s in amap.segments_for(f.file_id):
            if s.kind == "diff_file":
                c = s.context
                files_out.append({"patch": f.path, "path": str(c.get("path", "")), "status": str(c.get("status", "")), "added": int(c.get("added", 0) or 0),
                                  "removed": int(c.get("removed", 0) or 0), "hunks": int(c.get("hunks", 0) or 0), "line": s.start_line, "seg_id": s.seg_id})
    if not files_out:
        return None
    return {"method": "typed_diff_rollup", "patches": [f.path for f in chosen], "files": files_out,
            "added": sum(x["added"] for x in files_out), "removed": sum(x["removed"] for x in files_out)}


# --- commits between two hashes in a log file ------------------------------------------------------------------------------
def typed_commit_range(amap: AttachmentMap, query: str) -> dict[str, Any] | None:
    """``What changed between candidate 766cb08 and the final commit 623c957?`` — when the question names two commit
    hashes and both resolve to lines of the same ``<sha> <subject>`` log (newest first, as ``git log --oneline`` writes
    it), the answer is the log lines after the older one up to and including the newer one, read from the map. Abstains
    when fewer than two hashes are named, when they do not meet in one log, or when a hash matches several lines."""
    shas = _shas_in(query)
    if len(shas) < 2:
        return None
    for f in amap.files:
        if f.status != "INCLUDED" or f.duplicate_of or f.path.lower().rsplit(".", 1)[-1] in ("patch", "diff"):
            continue
        for s in amap.segments_for(f.file_id):
            lines = s.text.split("\n")
            log = [(i, m.group(1).casefold(), m.group(2).strip()) for i, ln in enumerate(lines) if (m := _LOG_LINE_RE.match(ln.strip()))]
            if len(log) < 2:
                continue
            pos: dict[str, list[int]] = {}
            for k, (_i, sha, _subj) in enumerate(log):
                for q in shas:
                    if sha.startswith(q) or q.startswith(sha):
                        pos.setdefault(q, []).append(k)
            if len(pos) < 2:
                continue
            if any(len(v) != 1 for v in pos.values()):
                return None   # a hash matches several log lines: no deterministic range
            a, b = sorted(pos[q][0] for q in list(pos)[:2])
            commits = [{"sha": log[k][1], "subject": log[k][2], "line": s.start_line + log[k][0], "seg_id": s.seg_id} for k in range(a, b)]
            return {"method": "typed_commit_range", "path": f.path, "newer": log[a][1], "older": log[b][1], "commits": commits, "log_lines": len(log)}
    return None
