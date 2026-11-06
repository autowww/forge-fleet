"""DCE-03 task DAG: compile a RequestIR (DCE-01) against an AttachmentMap (DCE-02) into typed, dependency-explicit
nodes, and produce a GET-style JSON plan preview with dry-run retrieval. Library only — no endpoint, no mutation,
zero model calls (the preview records what *would* need a model as ``route_pref`` D1/D2).

Node kinds: inventory, parse_structure, lookup, extract, compare, aggregate, verify, summarize, recommend.
Route preference: D0 = deterministic answer from the map (no model) · D1 = deterministic retrieval, model phrases the
answer over verified spans · D2 = model reasoning over several verified spans (reconcile / summarize / recommend).
Nodes split at independently verifiable objectives (= IR goals), not sentences; a compare/reconcile goal fans out to
one lookup per source so each side is verifiable on its own. Exclusions, ordering and output shape are preserved.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from .attachment_map import AttachmentMap, Scope
from .ir import RequestIR
from .retrieval import VALUE_RE_FOR as _VALUE_RE_FOR, Retriever
from . import tables, verdicts
from .untrusted import scan_untrusted

DAG_VERSION = "forge-2b.task-dag.v1"
NODE_KINDS = ("inventory", "parse_structure", "lookup", "extract", "compare", "aggregate", "verify", "summarize", "recommend")
ROUTES = ("D0", "D1", "D2")


class DagError(ValueError):
    pass


@dataclass
class Node:
    id: str
    kind: str
    depends_on: list[str]
    inputs: list[str]                 # goal ids / node ids whose outputs feed this node
    output_schema: dict[str, Any]
    source_scope: dict[str, list[str]]   # {"files": [...], "exclude": [...]} — empty files = whole map
    route_pref: str
    budget: dict[str, int]            # {"tokens": …, "calls": …}
    evidence: dict[str, Any]          # {"min_spans": n, "must_cite": bool, "verified_pointers_only": True}
    failure: str                      # the unresolved condition reported when evidence is missing
    goal_id: str = ""
    query: str = ""
    constraints: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TaskDAG:
    version: str
    request_sha256: str
    map_id: str
    nodes: list[Node]
    order_constraints: list[list[str]]     # [[before_node, after_node], …] from explicit user ordering
    output_shape: list[str]
    exclusions: list[str]
    unresolved: list[dict[str, str]]       # carried verbatim from the IR
    route: str                             # IR routing.route
    model_calls_planned: int               # D1/D2 nodes count — the *planned* calls, none made here

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "request_sha256": self.request_sha256, "map_id": self.map_id, "nodes": [asdict(n) for n in self.nodes],
                "order_constraints": self.order_constraints, "output_shape": self.output_shape, "exclusions": self.exclusions,
                "unresolved": self.unresolved, "route": self.route, "model_calls_planned": self.model_calls_planned}

    def to_json(self, **kw: Any) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("sort_keys", True)
        return json.dumps(self.to_dict(), **kw)

    def validate(self) -> None:
        errors = sorted(VALIDATOR.iter_errors(self.to_dict()), key=lambda e: list(e.path))
        if errors:
            raise DagError(f"TaskDAG schema: {errors[0].message} at {'/'.join(map(str, errors[0].path))}")
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise DagError("duplicate node id")
        for n in self.nodes:
            for d in n.depends_on:
                if d not in ids:
                    raise DagError(f"{n.id} depends on unknown node {d}")
        self.topological_order()

    def topological_order(self) -> list[str]:
        indeg = {n.id: len(set(n.depends_on)) for n in self.nodes}
        children: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for n in self.nodes:
            for d in set(n.depends_on):
                children[d].append(n.id)
        ready = sorted(i for i, d in indeg.items() if d == 0)
        out: list[str] = []
        while ready:
            cur = ready.pop(0)
            out.append(cur)
            for c in children[cur]:
                indeg[c] -= 1
                if indeg[c] == 0:
                    ready.append(c)
                    ready.sort()
        if len(out) != len(self.nodes):
            raise DagError("dependency cycle")
        return out


# --- compiler ----------------------------------------------------------------------------------------------------------
_OP_TO_KIND = {"list": "inventory", "inspect": "parse_structure", "extract": "lookup", "find": "lookup", "count": "aggregate", "compare": "compare",
               "reconcile": "compare", "summarize": "summarize", "validate": "verify", "recommend": "recommend", "transform": "lookup", "audit": "verify"}
_ROUTE = {"inventory": "D0", "parse_structure": "D0", "lookup": "D1", "extract": "D1", "aggregate": "D1", "compare": "D1", "verify": "D1", "summarize": "D2", "recommend": "D2"}
_SCHEMA_FOR = {
    "inventory": {"type": "array", "items": {"path": "string", "status": "INCLUDED|SKIPPED", "bytes": "integer"}},
    "parse_structure": {"type": "object", "properties": {"files": "AttachmentMap.files", "segments": "count"}},
    "lookup": {"type": "object", "properties": {"answer": "string", "spans": ["seg_id"], "status": "FOUND|NOT_FOUND|NOT_RETRIEVED|SOURCE_UNREADABLE"}},
    "aggregate": {"type": "object", "properties": {"value": "number", "spans": ["seg_id"], "method": "typed_count|row_count|model"}},
    "compare": {"type": "object", "properties": {"sides": [{"source": "path", "value": "string", "spans": ["seg_id"]}], "verdict": "equal|differs|undetermined"}},
    "verify": {"type": "object", "properties": {"checks": [{"claim": "string", "spans": ["seg_id"], "result": "pass|fail|unverifiable"}]}},
    "summarize": {"type": "object", "properties": {"summary": "string", "spans": ["seg_id"]}},
    "recommend": {"type": "object", "properties": {"recommendation": "string", "grounds": ["node_id"]}},
}


def compile_dag(ir: RequestIR, amap: AttachmentMap) -> TaskDAG:
    nodes: list[Node] = []
    all_cons = list(ir.constraints) + [c for g in ir.goals for c in g.constraints]
    exclusions = list(dict.fromkeys(c.value for c in all_cons if c.kind == "exclusion"))
    output_shape = list(dict.fromkeys(c.value for c in all_cons if c.kind == "output_shape"))
    # "do not quote/use/read the README" is a negation in the IR; when it names a file it is a source exclusion for retrieval
    source_negations = [c.value for c in all_cons if c.kind == "negation" and _NEG_SOURCE_RE.search(c.value)]
    excl_files = _files_in(exclusions + source_negations, amap)
    exclusions = list(dict.fromkeys(exclusions + [v for v in source_negations if _files_in([v], amap)]))
    has_files = any(f.status == "INCLUDED" for f in amap.files)
    root_id = "n0_inventory"
    nodes.append(Node(root_id, "inventory", [], [], _SCHEMA_FOR["inventory"], {"files": [], "exclude": [], "focus": []}, "D0", {"tokens": 0, "calls": 0},
                      {"min_spans": 0, "must_cite": False, "verified_pointers_only": True}, "attachment map unavailable", query="manifest"))
    struct_id = None
    if has_files:
        struct_id = "n1_parse_structure"
        nodes.append(Node(struct_id, "parse_structure", [root_id], [root_id], _SCHEMA_FOR["parse_structure"], {"files": [], "exclude": [], "focus": []}, "D0",
                          {"tokens": 0, "calls": 0}, {"min_spans": 0, "must_cite": False, "verified_pointers_only": True}, "no readable file in the archive"))
    goal_node: dict[str, str] = {}
    order_constraints: list[list[str]] = []
    prev_ordered: str | None = None
    merged_into, query_override = _merge_pronoun_clauses(ir)
    for g in sorted(ir.goals, key=lambda g: (g.order_index, g.id)):
        if g.id in merged_into:
            goal_node[g.id] = goal_node[merged_into[g.id]]
            continue
        qtext = query_override.get(g.id, g.span.text)
        kind = _OP_TO_KIND.get(g.operator, "lookup")
        words = re.findall(r"\w+", g.span.text)
        if g.operator == "inspect" and not (any(t.kind == "file" for t in g.targets) and len(words) <= 4):
            kind = "lookup"   # "check the health port" is a lookup; "inspect README.md" is structure
        hard, soft = [], []
        for t in g.targets:
            if t.kind == "file" and t.resolved:
                (hard if _is_literal_mention(t.span.text, t.value) else soft).append(t.value)
            elif t.kind == "file_group":
                soft.extend(t.candidates)
        if kind == "compare" and len(hard) < 2:   # one named side: the other side is somewhere else in the map
            soft, hard = sorted(dict.fromkeys(hard + soft)), []
        scope_files = sorted(dict.fromkeys(hard))
        scope = {"files": scope_files, "exclude": sorted(excl_files), "focus": sorted(dict.fromkeys(soft))}
        deps = [struct_id or root_id]
        for d in g.depends_on:
            if d in goal_node:
                deps.append(goal_node[d])
        gcons = [{"kind": c.kind, "value": c.value} for c in g.constraints]
        negated = g.polarity == "negative"
        base_id = f"{g.id}_{kind}"
        if kind == "compare" and len(scope_files) >= 2:
            side_ids = []
            for i, f in enumerate(scope_files, 1):
                sid = f"{g.id}_lookup_{i}"
                nodes.append(Node(sid, "lookup", deps, [g.id], _SCHEMA_FOR["lookup"], {"files": [f], "exclude": scope["exclude"], "focus": []}, "D1",
                                  {"tokens": 800, "calls": 0}, {"min_spans": 1, "must_cite": True, "verified_pointers_only": True},
                                  f"no span in {f} answers '{qtext[:60]}' → side undetermined", g.id, qtext, gcons))
                side_ids.append(sid)
            route = "D2" if g.operator == "reconcile" else "D1"
            nodes.append(Node(base_id, "compare", side_ids, side_ids, _SCHEMA_FOR["compare"], scope, route, {"tokens": 1200, "calls": 1},
                              {"min_spans": 2, "must_cite": True, "verified_pointers_only": True},
                              "fewer than two verified sides → verdict undetermined (never guessed)", g.id, qtext, gcons))
        else:
            route = _ROUTE[kind]
            if kind == "aggregate" and ((not scope_files and manifest_count(amap, qtext) is not None)
                                        or (_typed_count_possible(scope_files, amap) and typed_count(amap, scope_files, qtext) is not None)):
                route = "D0"   # only when the deterministic count will actually fire; otherwise the model path keeps its call budget
            if kind == "verify" and g.operator == "audit":
                route = "D0"
            calls = 0 if route == "D0" else 1
            failure = {"inventory": "manifest unavailable", "parse_structure": "file unreadable", "lookup": "no verified span → NOT_RETRIEVED / NOT_FOUND per retrieval status",
                       "aggregate": "no typed rows/keys to count → undetermined", "compare": "second source missing → undetermined",
                       "verify": "claim has no span → unverifiable", "summarize": "no readable spans → nothing to summarize",
                       "recommend": "upstream nodes unresolved → no recommendation"}[kind]
            if negated:
                failure = "negated goal: must NOT be performed; node exists only to record the prohibition"
                route, calls = "D0", 0
            nodes.append(Node(base_id, kind, deps, [g.id], _SCHEMA_FOR[kind], scope, route, {"tokens": 0 if calls == 0 else (600 if kind != "summarize" else 1500), "calls": calls},
                              {"min_spans": 0 if kind in ("inventory", "parse_structure") or negated else 1, "must_cite": kind not in ("inventory", "parse_structure"),
                               "verified_pointers_only": True}, failure, g.id, qtext, gcons))
        goal_node[g.id] = base_id
        if any(c.kind in ("order", "precondition") for c in g.constraints) or g.depends_on:
            if prev_ordered and prev_ordered != base_id:
                order_constraints.append([prev_ordered, base_id])
        prev_ordered = base_id
    # recommend/summarize nodes without explicit deps depend on every other goal node (they reason over the rest)
    for n in nodes:
        if n.kind in ("recommend",) and len(n.depends_on) <= 1:
            others = [m.id for m in nodes if m.goal_id and m.id != n.id and m.kind != "recommend"]
            n.depends_on = sorted(set(n.depends_on + others))
    planned = sum(n.budget["calls"] for n in nodes)
    dag = TaskDAG(DAG_VERSION, ir.prompt_sha256, amap.map_id, nodes, order_constraints, output_shape, exclusions,
                  [{"text": u.span.text, "reason": u.reason} for u in ir.unresolved], ir.routing.route, planned)
    dag.validate()
    return dag


def _is_literal_mention(mention: str, path: str) -> bool:
    """True when the user named the file itself (extension present, exact basename, or an upper-case doc name like README);
    False for stem-like words ("the service", "the config") that only *suggest* a file → soft focus, not a hard scope."""
    base = path.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0]
    m = mention.strip().strip("\"'`“”‘’")
    if "." in m and (m.casefold().endswith(base.casefold()) or base.casefold() in m.casefold()):
        return True
    if m.casefold() in (base.casefold(), stem.casefold()) and (m.isupper() or m.casefold() in ("readme", "changelog", "license", "notice", "makefile", "dockerfile")):
        return True
    return False


def typed_compare(amap: AttachmentMap, files: list[str]) -> dict[str, Any] | None:
    """Deterministic D0 key-wise diff between two config files (YAML/JSON/INI): differing values with both spans, identical
    keys, keys only on one side. None unless exactly two config files with key segments are given."""
    sides = []
    for p in files:
        for f in amap.files_by_path(p):
            if f.status == "INCLUDED" and f.language in ("yaml", "json", "toml", "ini"):
                keys = {}
                for s in amap.segments_for(f.file_id):
                    if s.kind == "key" and s.context.get("key") and "value" in s.context:
                        keys[s.context.get("path") or s.context.get("pointer") or s.context["key"]] = s
                sides.append((f, keys))
                break
    if len(sides) != 2:
        return None
    (fa, ka), (fb, kb) = sides
    differs, same = [], []
    for k in sorted(set(ka) & set(kb)):
        a, b = ka[k], kb[k]
        rec = {"key": k, "sides": [{"path": fa.path, "line": a.start_line, "seg_id": a.seg_id, "value": a.context["value"]},
                                   {"path": fb.path, "line": b.start_line, "seg_id": b.seg_id, "value": b.context["value"]}]}
        (differs if a.context["value"] != b.context["value"] else same).append(rec)
    return {"method": "typed_key_diff", "differs": differs, "same": same,
            "only_in": {fa.path: sorted(set(ka) - set(kb)), fb.path: sorted(set(kb) - set(ka))},
            "verdict": "differs" if differs or (set(ka) ^ set(kb)) else "equal"}


_NEG_SOURCE_RE = re.compile(r"\b(quote|quoting|use|using|read|reading|cite|citing|include|including|consult|look at|rely on|open)\b", re.I)


_MANIFEST_COUNT_RE = re.compile(r"\b(files?|documents?|entries|folders?|directories)\b", re.I)
_PACKAGE_NOUN_RE = re.compile(r"\b(package|archive|zip|bundle|attachment|upload(?:ed)?|does (?:it|this) (?:contain|have|hold|include))\b", re.I)
_CONTENT_COUNT_RE = re.compile(r"\b(patch|diff|commit|chang\w*|modif\w*|touch\w*|delet\w*|add\w*|remov\w*|renam\w*|fail\w*|pass\w*|in\s+(?:the\s+)?[\w.-]+\.\w{1,5})\b", re.I)


def manifest_count(amap: AttachmentMap, query: str) -> dict[str, Any] | None:
    """D0 count of the archive itself ("How many files does the package contain?", live K29 2026-11-06: 153 JSON leaves
    went to the model, which found no answer). Files, or folders, from the attachment map — never from file contents.
    Guarded: the question must be about the package (archive/zip/bundle/"does it contain") and not about what a patch,
    commit or a named file changed/contains — those are content questions and stay with the retriever."""
    m = _MANIFEST_COUNT_RE.search(query)
    if not m or not _PACKAGE_NOUN_RE.search(query) or _CONTENT_COUNT_RE.search(query):
        return None
    noun = m.group(1).casefold()
    if noun.startswith(("folder", "director")):
        dirs = {"/".join(f.path.split("/")[:i]) for f in amap.files for i in range(1, f.path.count("/") + 1)}
        return {"value": len(dirs), "method": "manifest_count:folders", "spans": [], "lines": [], "path": "", "detail": ", ".join(f"`{d}/`" for d in sorted(dirs)[:12])}
    inc = [f for f in amap.files if f.status == "INCLUDED"]
    skipped = [f for f in amap.files if f.status != "INCLUDED"]
    detail = f"{len(inc)} readable" + (f", {len(skipped)} skipped ({', '.join(sorted({f.status for f in skipped}))})" if skipped else "")
    return {"value": len(amap.files), "method": "manifest_count:files", "spans": [], "lines": [], "path": "", "detail": detail}


def typed_count(amap: AttachmentMap, files: list[str], query: str) -> dict[str, Any] | None:
    """Deterministic D0 count over CSV rows: rows whose cells equal a query word (casefold) — e.g. 'failed' → status=failed.
    Without a matching filter word, counts all data rows. Returns None when no CSV is in scope. A count of the archive's
    own files/folders (no file named) is answered from the map (``manifest_count``)."""
    if not files:
        mc = manifest_count(amap, query)
        if mc is not None:
            return mc
    words = {w.casefold() for w in re.findall(r"\w+", query)}
    csvs = [f for f in amap.files if f.status == "INCLUDED" and f.language in ("csv", "tsv") and (not files or f.path in files)]
    asks_rows = bool(words & {"rows", "entries", "records", "lines"})
    for f in csvs:
        rows = [s for s in amap.segments_for(f.file_id) if s.kind == "row"]
        if not rows:
            continue
        filters: dict[str, str] = {}
        for s in rows:
            for col, val in s.context.get("cells", {}).items():
                if isinstance(val, str) and val.casefold() in words and not val.isdigit():
                    filters[col] = val.casefold()
        if not filters and (not files or f.path not in files) and not (asks_rows and len(csvs) == 1):
            return None   # an unnamed table and no cell word in the question: "how many users" must not become a row count
            # — unless the question literally asks for rows and there is exactly one table it can mean; the guard below
            # still requires its other words ("test results") to be the table's name (oracle C081)
        # the question may ask for rows *with a property* this table does not carry ("how many gates passed in the public
        # re-run" over True/False cells — live K08 2026-11-06 answered the row count 10 for 5; "how many tests passed in the
        # public re-run" over a status column counts the wrong run): every content word must be a header / file-name /
        # filter word, else the count is not this operator's to make (the verdict-column filter or the model path answers it)
        header = next((s for s in amap.segments_for(f.file_id) if s.kind == "header"), None)
        cols = [str(c) for c in (header.context.get("columns", []) if header else [])]
        explained = set().union(*(tables._words(c) for c in cols)) if cols else set()
        explained |= tables._words(f.path.replace("/", " ").replace(".", " ")) | set(filters.values()) | {"rows", "row", "entries", "entry", "records", "record", "lines", "line", "items", "item", "listed", "total"}
        cw = tables._content_words(query)
        if tables._guard(cw, explained | tables._GENERIC):
            return None
        if any(w in (tables._FILTER_POS | tables._FILTER_NEG) and w not in filters.values() for w in cw):
            return None   # "passed" over a `public_pass` header is a verdict to filter by, not a header word (K08): the verdict-column filter answers it
        matched = [s for s in rows if all(str(s.context["cells"].get(c, "")).casefold() == v for c, v in filters.items())]
        return {"value": len(matched), "method": "row_count" + ("" if not filters else ":" + ",".join(f"{c}={v}" for c, v in sorted(filters.items()))),
                "spans": [s.seg_id for s in matched], "path": f.path, "lines": [s.start_line for s in matched], "header_line": next((s.start_line for s in amap.segments_for(f.file_id) if s.kind == "header"), None)}
    return None


def _files_in(values: list[str], amap: AttachmentMap) -> list[str]:
    out = []
    for v in values:
        low = v.casefold()
        for f in amap.files:
            base = f.path.rsplit("/", 1)[-1]
            if f.path.casefold() in low or base.casefold() in low or base.rsplit(".", 1)[0].casefold() in low.split():
                out.append(f.path)
    return sorted(set(out))


def _typed_count_possible(files: list[str], amap: AttachmentMap) -> bool:
    cands = [f for f in amap.files if (not files or f.path in files) and f.status == "INCLUDED"]
    tabular = [f for f in cands if f.language in ("csv", "tsv") or f.role_hints == ["inventory"]]
    # a named file, or exactly one tabular file in the whole map (live finding 2026-11-05: "Count the failed tests" went to the model)
    return bool(tabular) and (bool(files) or len(tabular) == 1)


_VERSIONED_RE = re.compile(r"(?:^|[._-])v?\d+(?:[._]\d+)*(?=\.[A-Za-z]+$|$)|\b(?:old|legacy|prev|previous|backup|bak)\b", re.I)
_RECENT_RE = re.compile(r"\b(latest|newest|most recent|current)\b", re.I)
_OLDER_RE = re.compile(r"\b(older|oldest|previous|earlier|old)\b", re.I)
_KEY_SPLIT_RE = re.compile(r"[^0-9a-z]+")
_UNIT_WORDS = frozenset("mb gb kb megabytes gigabytes kilobytes bytes ms s sec secs seconds minutes min mins hours days percent".split())
_BOOL_NULL_VALUES = frozenset({"true", "false", "yes", "no", "on", "off", "null", "none", "~", ""})
_YES_NO_Q_RE = re.compile(r"^(?:is|are|was|were|does|do|did|has|have|had|can|could|should|will|would|must|чи|is it|whether)\b", re.I)
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_SEMVER_RE = re.compile(r"(?<![\w.])v?(\d+)\.(\d+)(?:\.(\d+))?(?![\w.])")
_NEWEST_RE = re.compile(r"\b(newest|latest|most recent|current|last)\b", re.I)
_OLDEST_RE = re.compile(r"\b(oldest|earliest|very first)\b", re.I)
_PREVIOUS_RE = re.compile(r"\b(older|previous|earlier|prior|preceding|penultimate|second[- ]latest|second[- ]newest)\b", re.I)
_SECTION_CUE_RE = re.compile(r"\b(entry|entries|release|releases|version|versions|changelog|change|changes|update|updates|section|sections|note|notes|item|items|one|ones|record|records)\b", re.I)


def typed_dated_sections(amap: AttachmentMap, files: list[str], query: str) -> dict[str, Any] | None:
    """Deterministic D0 answer for "the newest / oldest / older entry" over a markdown file whose same-level headings carry
    an ISO date or a version (changelogs, release notes). Entries are ordered by date (else version) descending; the
    selector in the question picks one — *newest/latest* → first, *oldest/earliest* → last, *older/previous* → the one
    right after the newest when there are exactly two, otherwise every entry is listed and none is chosen. The chosen
    entry is returned with its heading line and the body lines under it as verified pointers (live finding 2026-11-05:
    the 2B model cited a changelog body line as "the newest entry" and never found "the older one"). None when the
    question has no such selector, or no (or more than one unnamed) file has at least two dated headings."""
    sel = "newest" if _NEWEST_RE.search(query) else "oldest" if _OLDEST_RE.search(query) else "previous" if _PREVIOUS_RE.search(query) else None
    if sel is None:
        return None
    qlow = query.casefold()
    cands = []
    for f in amap.files:
        if f.status != "INCLUDED" or (files and f.path not in files) or f.language not in ("markdown", "md", "text", "rst"):
            continue
        stem = f.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].casefold()
        if not (_SECTION_CUE_RE.search(query) or stem in qlow or f.path in files):
            continue   # "the current config" is a key question, not a dated-entry question
        segs = amap.segments_for(f.file_id)
        heads = [s for s in segs if s.kind == "heading" and (_ISO_DATE_RE.search(s.text) or _SEMVER_RE.search(s.text))]
        if len(heads) < 2:
            continue
        level = max(set(h.context.get("level", 0) for h in heads), key=lambda lv: sum(1 for h in heads if h.context.get("level", 0) == lv))
        heads = [h for h in heads if h.context.get("level", 0) == level]
        if len(heads) < 2:
            continue
        cands.append((f, segs, heads))
    if len(cands) != 1:
        return None   # nothing dated, or several dated files and the question names none of them
    f, segs, heads = cands[0]
    by_date = all(_ISO_DATE_RE.search(h.text) for h in heads)

    def key(h):
        if by_date:
            m = _ISO_DATE_RE.search(h.text)
            return tuple(int(x) for x in m.groups())
        m = _SEMVER_RE.search(h.text)
        return tuple(int(x or 0) for x in m.groups())

    ordered = sorted(heads, key=key, reverse=True)
    head_ids = {h.seg_id for h in heads}
    entries = []
    for h in ordered:
        body = []
        started = False
        for s in segs:
            if s.seg_id == h.seg_id:
                started = True
                continue
            if started:
                if s.kind == "heading" and (s.seg_id in head_ids or s.context.get("level", 0) <= h.context.get("level", 0)):
                    break
                body.append({"seg_id": s.seg_id, "line": s.start_line, "text": s.text})
        m = _ISO_DATE_RE.search(h.text) if by_date else _SEMVER_RE.search(h.text)
        entries.append({"seg_id": h.seg_id, "line": h.start_line, "text": h.text, "key": m.group(0), "body": body})
    if sel == "newest":
        chosen, note = [0], ""
    elif sel == "oldest":
        chosen, note = [len(entries) - 1], ""
    elif len(entries) == 2:
        chosen, note = [1], "older = the entry before the newest (two entries)"
    else:
        chosen, note = [], f"'older/previous' is ambiguous across {len(entries)} dated entries; all listed, none chosen"
    return {"method": "typed_dated_sections", "path": f.path, "ordered_by": "date" if by_date else "version", "selector": sel,
            "entries": entries, "chosen": chosen, "ambiguous": not chosen, "note": note}


def typed_key_lookup(amap: AttachmentMap, hits: list[Any], query: str, retriever: Retriever | None = None) -> dict[str, Any] | None:
    """Deterministic D0 answer for a lookup whose best-ranked hits are config *key* lines matching the question word or its
    curated alias (`exact_key` / `alias_key` features) and whose every content word is explained by that key, its aliases,
    a unit word or a file path (anything else — "after confirming the sentinel, tell me the name" — stays on the model path).
    One file → the value with its pointer. The same key in several files → files the question names; else the unversioned
    file for current/latest, the versioned one for older/previous; otherwise every value is listed and none is chosen
    (live finding 2026-11-05: the 2B model answered the memory limit from `service.v1.yaml` while `service.yaml` was also
    in its excerpts). Non-key hits that literally carry the chosen value are returned as corroborating pointers."""
    from . import aliases as _al   # local import: aliases depends on retrieval helpers, dag must stay importable first
    from .retrieval import STOPWORDS, fold, norm
    segs = {s.seg_id: s for s in amap.segments}
    groups: dict[str, list[tuple[float, Any]]] = {}
    for h in hits:
        feats = getattr(h, "features", {}) or {}
        if not (feats.get("exact_key") or feats.get("alias_key")):
            continue
        s = segs.get(getattr(h, "seg_id", "") or "")
        if s is None or s.kind != "key" or not s.context.get("key") or "value" not in s.context:
            continue
        groups.setdefault(str(s.context["key"]).casefold(), []).append((float(getattr(h, "score", 0.0)), s))
    if not groups:
        return None
    key, rows = max(groups.items(), key=lambda kv: sum(sc for sc, _ in kv[1]))
    if not hits or getattr(hits[0], "seg_id", None) not in {s.seg_id for _, s in rows}:
        return None   # the best-ranked line is not that key: leave the decision to the verified-quote path
    files = {f.file_id: f for f in amap.files}
    # a boolean / null leaf cannot answer a who / which / what-value question — only a yes-no question
    # (live finding 2026-11-06, G1R3A package: "Who labelled the blind set?" was answered `labelled = true`,
    # "Which commit froze the blind set?" with three `frozen: true` leaves)
    if all(str(s.context.get("value", "")).strip().casefold() in _BOOL_NULL_VALUES for _, s in rows) and not _YES_NO_Q_RE.match(query.strip()):
        return None
    # every content word of the question must be explained by the key, its aliases, a unit or the path of a file that
    # carries the key (not every path in the archive: in a 60-file package that explains almost any word)
    explained = set(_KEY_SPLIT_RE.split(key)) | _UNIT_WORDS | {"older", "oldest", "previous", "earlier", "old", "latest", "newest", "recent", "current"}
    table = getattr(retriever, "alias_table", None)
    for ph in _al.expansions_for_key(key, table) if table is not None else _al.expansions_for_key(key):
        explained |= set(_KEY_SPLIT_RE.split(norm(ph)))
    for fid in {s.file_id for _, s in rows}:
        explained |= set(_KEY_SPLIT_RE.split(files[fid].path.casefold()))
    if retriever is not None:
        terms, expanded, typo, _anchors = retriever.analyze(query)
        for k, phrases in expanded.items():
            if k.casefold() == key:
                explained |= {w for p in phrases for w in p.split()}
        words = [typo.get(t, t) for t in terms]
    else:
        words = [w for w in _KEY_SPLIT_RE.split(norm(query)) if w]
    from .lexicon import REQUEST_WORDS
    leftover = [w for w in words if w and w not in explained and fold(w) not in explained and w not in REQUEST_WORDS and w not in STOPWORDS
                and not w.isdigit() and not any(w.startswith(e[:5]) and len(e) > 4 for e in explained)]
    if leftover:
        return None
    best_by_file: dict[str, Any] = {}
    for sc, s in sorted(rows, key=lambda x: -x[0]):
        best_by_file.setdefault(s.file_id, s)
    values = [{"path": files[fid].path, "line": s.start_line, "seg_id": s.seg_id, "value": str(s.context["value"])} for fid, s in best_by_file.items()]
    values.sort(key=lambda v: v["path"])
    qlow = query.casefold()
    named = [v for v in values if v["path"].casefold() in qlow or v["path"].rsplit("/", 1)[-1].casefold() in qlow]
    chosen, note = values, ""
    if named:
        chosen, note = named, "" if len(named) == len(values) else f"file(s) named in the question: {', '.join(v['path'] for v in named)}"
    elif len(values) > 1 and len({v["value"] for v in values}) > 1:
        unversioned = [v for v in values if not _VERSIONED_RE.search(v["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0])]
        versioned = [v for v in values if v not in unversioned]
        if _RECENT_RE.search(query) and len(unversioned) == 1:
            chosen, note = unversioned, "current = the unversioned file"
        elif _OLDER_RE.search(query) and len(versioned) == 1:
            chosen, note = versioned, "older = the versioned file"
        else:
            note = f"the key appears in {len(values)} files with different values and the question does not say which; all shown, none chosen"
    chosen_vals = {v["value"] for v in chosen}
    corroborating = []
    key_seg_ids = {v["seg_id"] for v in values}
    for h in hits:
        sid = getattr(h, "seg_id", "") or ""
        if sid in key_seg_ids or sid not in segs:
            continue
        text = getattr(h, "text", "") or segs[sid].text
        if any(re.search(rf"(?<![\w-])(?<!\d\.){re.escape(v)}(?![\w-])(?!\.\d)", text) for v in chosen_vals if len(v) > 1):
            corroborating.append({"path": getattr(h, "path", files[segs[sid].file_id].path), "line": getattr(h, "line", segs[sid].start_line), "seg_id": sid})
    return {"method": "typed_key_lookup", "key": key, "values": chosen, "all_values": values, "corroborating": corroborating,
            "ambiguous": len(chosen) > 1 and len(chosen_vals) > 1, "note": note}


_TYPED_VALUE_Q_RE = re.compile(r"^\s*(?:which|what)\s+(?:is\s+the\s+|was\s+the\s+)?(commit|hash|sha|version|date|port|tag|branch)\b", re.I)


def typed_label_value(amap: AttachmentMap, hits: list[Any], query: str) -> dict[str, Any] | None:
    """Deterministic D0 answer for "which commit / version / date … is the X?" when the best-ranked line is a `label: value`
    line of prose or a text file whose label words explain every content word of the question and whose value is of the
    asked type (live M13 G1R3E, 2026-11-06: `candidate_frozen_at: 21d608c` ranked first for "Which commit is the frozen
    candidate?", and the model quoted another commit's row of the commit table). Several such lines with different values
    are all listed and none chosen; anything the label does not explain leaves the model path untouched."""
    from .retrieval import _LABEL_LINE_RE, STOPWORDS, fold, norm, stems_of
    from . import tables as _tables
    m = _TYPED_VALUE_Q_RE.match(query)
    if not m or not hits:
        return None
    type_word = m.group(1).casefold()
    val_re = re.compile(_VALUE_RE_FOR[type_word], re.I)
    need = [w for w in _tables._content_words(query) if w != type_word and w not in ("commit", "commits")]
    if not need:
        return None

    def _label_words(label: str) -> set[str]:
        return {fold(w) for w in re.findall(r"[A-Za-z0-9]+", label) if len(w) > 1} - STOPWORDS

    def _explains(lw: set[str], w: str) -> bool:
        return any(w == e or (len(w) >= 4 and len(e) >= 4 and (w.startswith(e[:4]) or e.startswith(w[:4]))) or any(e.startswith(st) for st in stems_of(w)) for e in lw)

    segs = {s.seg_id: s for s in amap.segments}
    files = {f.file_id: f for f in amap.files}
    found: list[dict[str, Any]] = []
    for h in hits:
        text = getattr(h, "text", "") or ""
        lm = _LABEL_LINE_RE.match(text)
        if not lm or (getattr(h, "features", None) or {}).get("scoped_under"):
            continue   # a line nested under a label the question does not name is that label's value (retrieval `scoped_under`)
        # the file's name is the outermost label of a top-level line: `Candidate commit: 620c217` in `CANDIDATE_FREEZE.txt`
        # says "frozen candidate" between the two (live L14 G1R3D, 2026-11-07)
        lw = _label_words(lm.group(1)) | (_label_words(h.path.replace("/", " ").replace(".", " ").replace("_", " ")) if text[:1].strip() else set())
        if not all(_explains(lw, w) for w in need):
            continue
        rest = text[lm.end() - 1:]
        vals = val_re.findall(rest)
        if len(set(vals)) != 1:
            continue
        found.append({"path": h.path, "line": h.line, "seg_id": h.seg_id, "value": vals[0], "key": lm.group(1).strip()})
    if not found or found[0]["seg_id"] != getattr(hits[0], "seg_id", None):
        return None   # the best-ranked line is not such a label line: the verified-quote path decides
    values = list({(v["path"], v["line"]): v for v in found}.values())
    distinct = {v["value"] for v in values}
    chosen = values if len(distinct) > 1 else values[:1]
    note = "" if len(distinct) == 1 else f"{len(values)} labelled lines carry different {type_word}s and the question does not say which; all shown, none chosen"
    corroborating = []
    for h in hits:
        if any(h.seg_id == v["seg_id"] for v in values):
            continue
        text = getattr(h, "text", "") or (segs[h.seg_id].text if h.seg_id in segs else "")
        if len(distinct) == 1 and re.search(rf"(?<![\w-]){re.escape(next(iter(distinct)))}(?![\w-])", text):
            corroborating.append({"path": h.path, "line": h.line, "seg_id": h.seg_id})
    return {"method": "typed_label_value", "key": values[0]["key"], "values": chosen, "all_values": values, "corroborating": corroborating[:4],
            "ambiguous": len(distinct) > 1, "note": note}


# --- plan preview (GET-style, read-only) -----------------------------------------------------------------------------------
def _row_continuation(ir: RequestIR, amap: AttachmentMap, n: Any, done: list[dict[str, Any]]) -> dict[str, Any] | None:
    goal = next((g for g in ir.goals if g.id == n.goal_id), None)
    if goal is None:
        return None
    for prev in reversed(done):
        tt = prev.get("typed_table")
        if not tt or tt.get("method") != "typed_table_row" or not prev.get("id", "").startswith(("g",)):
            continue
        pg = next((g for g in ir.goals if g.id == prev["id"].split("_", 1)[0]), None)
        if pg is None or pg.span.end > goal.span.start or re.search(r"[.?!]", ir.text[pg.span.end:goal.span.start]):
            continue   # not the same sentence
        return tables.typed_table_row(amap, f"{tt['label']} {n.query}", continuation_of=tt)
    return None


_WHICH_FILE_RE = re.compile(r"^\s*(which|what)\s+(\w+\s+)?files?\b", re.I)


_PRONOUN_CLAUSE_RE = re.compile(r"^\W*(?:and|,|;|then)?\s*(?:what|which|how many|how much|who|when|where)?\s*\w*\s*(?:\w+\s+){0,3}?\b(it|its|they|their|them|those|that one|the same)\b", re.I)


def _merge_pronoun_clauses(ir: RequestIR) -> tuple[dict[str, str], dict[str, str]]:
    """A coordinated clause whose subject is a pronoun of the previous clause is not a question of its own: "What was the
    utterance of J165 **and what flag did it get**?" / "How many cases are in the sealed set **and what are their ids**?"
    (live M21 / M18 G1R3E, 2026-11-06) were split into a goal and a pronoun goal that retrieved over the whole package with
    `it` / `their` unresolved. The pronoun goal is merged into the previous goal of the same sentence: one node, whose
    query is the sentence span from the first clause to the pronoun clause, so a table row with both named columns or a
    line carrying both facts answers it. Clauses that name their own subject (K09's "what was observed in the blind run")
    are left split; nothing crosses a sentence boundary."""
    goals = sorted(ir.goals, key=lambda g: (g.order_index, g.id))
    merged: dict[str, str] = {}
    override: dict[str, str] = {}
    for prev, g in zip(goals, goals[1:]):
        if prev.id in merged:
            continue
        between = ir.text[prev.span.end:g.span.start]
        if re.search(r"[.?!]", between) or len(between) > 12:
            continue
        if not _PRONOUN_CLAUSE_RE.match(g.span.text) or any(t.kind == "file" and t.resolved for t in g.targets):
            continue
        if _OP_TO_KIND.get(g.operator, "lookup") not in ("lookup", "aggregate", "verify") or _OP_TO_KIND.get(prev.operator, "lookup") not in ("lookup", "aggregate", "verify"):
            continue
        head = override.get(prev.id, prev.span.text)
        override[prev.id] = (head + between + g.span.text).strip()
        merged[g.id] = prev.id
    return merged, override


def typed_file_which(ir: RequestIR, amap: AttachmentMap, n: Node) -> dict[str, Any] | None:
    """"Which file lists the per-case blind results as CSV?" (live L30 G1R3D, 2026-11-06): the question asks for a *file*
    and names file groups the IR resolved (``blind`` → the blind/ files, ``csv`` → the .csv files). The files that belong
    to every named group are the answer, read from the manifest with no model call — one to six of them; a question
    that names a file outright, or whose groups meet in no file or in too many, keeps the model path."""
    if not n.query or not _WHICH_FILE_RE.match(n.query) or n.source_scope["files"]:
        return None
    g = next((g for g in ir.goals if g.id == n.goal_id), None)
    if g is None:
        return None
    groups = [(t.value, set(t.candidates)) for t in g.targets if t.kind == "file_group" and t.candidates]
    if not groups:
        return None
    paths = set.intersection(*(c for _v, c in groups))   # candidates are paths
    by_path = {f.path: f for f in amap.files if f.status == "INCLUDED"}
    files = [by_path[p] for p in sorted(paths) if p in by_path]
    if not files or len(files) > 6:
        return None
    entries = []
    for f in files:
        segs = amap.segments_for(f.file_id)
        if not segs:
            return None
        entries.append({"path": f.path, "line": segs[0].start_line, "seg_id": segs[0].seg_id, "segments": len(segs)})
    return {"method": "typed_file_which", "groups": [v for v, _c in groups], "entries": entries}


def plan_preview(ir: RequestIR, amap: AttachmentMap, scope: Scope, *, max_hits: int = 8, retriever: Retriever | None = None) -> dict[str, Any]:
    """Deterministic dry run: DAG + per-node retrieval (status, ranked verified spans) + untrusted-instruction scan. No model call."""
    dag = compile_dag(ir, amap)
    R = retriever or Retriever(amap)
    nodes_out = []
    for n in dag.nodes:
        entry: dict[str, Any] = {"id": n.id, "kind": n.kind, "route_pref": n.route_pref, "depends_on": n.depends_on}
        if n.goal_id and _is_audit(ir, n.goal_id):
            findings = scan_untrusted(amap, files=n.source_scope["files"] or None)
            entry["untrusted_scan"] = [asdict(f) for f in findings]
            entry["status"] = "REFUSE_UNTRUSTED" if findings else "CLEAN"
        elif n.query and n.kind in ("lookup", "aggregate", "compare", "verify", "summarize"):
            if n.kind == "aggregate" and n.route_pref == "D0":
                tc = typed_count(amap, n.source_scope["files"], n.query)
                if tc:
                    entry["typed_count"] = tc
            if n.kind == "compare" and len(n.source_scope["files"]) == 2:
                td = typed_compare(amap, n.source_scope["files"])
                if td:
                    entry["typed_compare"] = td
                    entry["route_pref"] = "D0" if td["verdict"] else n.route_pref
            res = R.search(n.query, scope_files=n.source_scope["files"] or None, focus_files=n.source_scope.get("focus") or None,
                           exclude_files=n.source_scope["exclude"] or None, max_hits=max_hits)
            entry["status"] = res.status
            entry["strategy"] = res.strategy
            entry["coverage"] = res.coverage
            # D0 typed operators over tables and patches (Phase 2): a named row, an extreme over a column, a patch rollup —
            # each abstains unless every content word of the question is explained by the table / patch it answers from
            typed_table = (tables.typed_commit_range(amap, n.query) or tables.typed_table_filter(amap, n.query) or tables.typed_table_predicate(amap, n.query) or tables.typed_table_select(amap, n.query) or tables.typed_table_extreme(amap, n.query) or tables.typed_table_row(amap, n.query)
                           or tables.typed_diff_rollup(amap, n.query)) if n.kind != "summarize" else None
            if typed_table is None and n.kind == "lookup":
                typed_table = typed_file_which(ir, amap, n)
            if typed_table is None and n.kind == "lookup":
                # coordination ellipsis (live K09 2026-11-06): "What is the threshold for explicit-mutation recall and what was
                # observed in the blind run?" splits into a row goal and an elliptical goal that names no row — the model
                # answered the second with a number from another line. When the elliptical goal is in the same sentence as
                # a goal the row operator answered, and its words are column / heading words of that table, it is read from
                # the same row (zero calls); any other word keeps the model path.
                typed_table = _row_continuation(ir, amap, n, nodes_out)
            typed_verdict = verdicts.typed_verdict(amap, n.source_scope["files"], n.query) if not typed_table and n.kind in ("lookup", "verify") else None
            if typed_table:
                entry["typed_table"] = typed_table
                entry["route_pref"] = "D0"
            elif typed_verdict:
                # D0: "what is the verdict / decision / status" is read from the labelled line(s), no model call
                entry["typed_verdict"] = typed_verdict
                entry["route_pref"] = "D0"
            elif n.kind == "lookup":   # goal deps on a lookup are ordering only ("first … then"), not data flow
                ts = typed_dated_sections(amap, n.source_scope["files"], n.query)
                if ts:
                    entry["typed_dated_sections"] = ts
                    entry["route_pref"] = "D0"
                elif res.status == "FOUND" and res.hits:
                    tk = typed_key_lookup(amap, res.hits, n.query, R) or typed_label_value(amap, res.hits, n.query)
                    if tk:
                        entry["typed_key_lookup"] = tk
                        entry["route_pref"] = "D0"
            spans = []
            for h in res.hits:
                loc = amap.resolve(h.seg_id, scope) if h.seg_id else None   # raises if the pointer does not round-trip
                spans.append({"seg_id": h.seg_id, "path": h.path, "line": h.line, "score": h.score, "features": h.features, "verified": loc is not None})
            entry["spans"] = spans
        nodes_out.append(entry)
    body = {"dag": dag.to_dict(), "preview": nodes_out, "order": dag.topological_order(), "model_calls_made": 0}
    body["preview_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return body


def _is_audit(ir: RequestIR, goal_id: str) -> bool:
    return any(g.id == goal_id and g.operator == "audit" for g in ir.goals)


# --- schema ------------------------------------------------------------------------------------------------------------------
_STR = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object", "additionalProperties": False,
    "required": ["version", "request_sha256", "map_id", "nodes", "order_constraints", "output_shape", "exclusions", "unresolved", "route", "model_calls_planned"],
    "properties": {
        "version": {"const": DAG_VERSION}, "request_sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}, "map_id": _STR,
        "nodes": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "kind", "depends_on", "inputs", "output_schema", "source_scope", "route_pref", "budget", "evidence", "failure", "goal_id", "query", "constraints"],
            "properties": {"id": _STR, "kind": {"enum": list(NODE_KINDS)}, "depends_on": {"type": "array", "items": _STR}, "inputs": {"type": "array", "items": _STR},
                           "output_schema": {"type": "object"}, "source_scope": {"type": "object", "required": ["files", "exclude"]},
                           "route_pref": {"enum": list(ROUTES)}, "budget": {"type": "object", "required": ["tokens", "calls"]},
                           "evidence": {"type": "object", "required": ["min_spans", "must_cite", "verified_pointers_only"]}, "failure": _STR,
                           "goal_id": _STR, "query": _STR, "constraints": {"type": "array"}}}},
        "order_constraints": {"type": "array", "items": {"type": "array", "items": _STR, "minItems": 2, "maxItems": 2}},
        "output_shape": {"type": "array", "items": _STR}, "exclusions": {"type": "array", "items": _STR},
        "unresolved": {"type": "array", "items": {"type": "object"}}, "route": _STR, "model_calls_planned": {"type": "integer", "minimum": 0},
    },
}
VALIDATOR = Draft202012Validator(SCHEMA)
