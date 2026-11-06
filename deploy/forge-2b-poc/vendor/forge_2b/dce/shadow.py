"""DCE-04: feature-flagged integration of the Deterministic Comprehension Engine with the legacy attachment lane.

``FORGE_2B_DCE_MODE``
  off     — (default) nothing from this module runs; the facade behaves exactly as before.
  shadow  — DCE parse → map → DAG → dry-run retrieval runs *beside* the legacy lane; the user-visible response is
            unchanged; a sanitized trace plus the legacy-vs-DCE route/evidence differences land under the run id.
  on      — tested attachment operations are answered through the DCE DAG with a merge/verification gate.
            D0 nodes (manifest, structure, typed count, typed key diff, untrusted scan, exhaustive NOT_FOUND) need no
            model; D1 nodes call the existing fixed-model Q2 contract over DCE-retrieved, map-verified spans; D2 nodes
            (summarize/recommend) get one bounded Q2 call over already-verified spans and are reported PARTIAL because
            quote correctness alone does not prove entailment. Anything else is reported UNSUPPORTED — never free chat.

The 10-K lane and the SOURCE/END_SOURCE fixture are not touched by any mode. Everything here is bounded: one semaphore,
a wall-clock budget for the deterministic stage, and a per-run model-call cap. Nothing in this module performs I/O.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from .. import attach, zipingest
from .attachment_map import AttachmentMap, Scope, build_attachment_map, warm_parse_cache
from .dag import TaskDAG, compile_dag, plan_preview
from .ir import RequestIR
from .parse import parse_request
from . import aliases, lexicon, retrieval
from .retrieval import Retriever
from .untrusted import Finding, refusal_text, scan_text

log = logging.getLogger("forge_2b.dce")

MODES = ("off", "shadow", "on")
TRACE_VERSION = "forge-2b.dce-trace.v1"
NODE_STATUSES = ("COMMITTED", "PARTIAL", "FAILED", "UNSUPPORTED", "SKIPPED")
RUN_STATUSES = ("COMMITTED", "PARTIAL", "FAILED")


def normalize_mode(value: str | None) -> str:
    v = (value or "off").strip().lower()
    return v if v in MODES else "off"


@dataclass(frozen=True)
class Budget:
    plan_ms: float = 1500.0       # deterministic stage (parse + map + DAG + dry-run retrieval) wall-clock cap; warm map ≈ 0.2 s
    max_hits: int = 8
    max_model_calls: int = 3      # per run, all D1/D2 nodes together
    max_attempts: int = 2         # per node, same as the legacy Q2 loop


# --- deterministic stage (shadow and on) ----------------------------------------------------------------------------------
@dataclass
class Plan:
    ir: RequestIR
    amap: AttachmentMap
    scope: Scope
    dag: TaskDAG
    preview: dict[str, Any]
    retriever: Retriever
    elapsed_ms: float


def warm_caches(ing: zipingest.Ingest) -> dict[str, Any]:
    """Called at ingest time (upload), off the question path: parse every file into the content-addressed parse cache
    and build the retrieval index once so the first question's plan stage is a lookup, not a multi-second build.
    Pure CPU, no model, nothing persisted; both caches are keyed by content, never by scope."""
    t0 = time.perf_counter()
    cold_files = warm_parse_cache(ing)
    amap = build_attachment_map([ing], Scope("forge-2b", "-", "warm"))
    Retriever(amap)
    return {"files_parsed_cold": cold_files, "segments": len(amap.segments), "ms": round((time.perf_counter() - t0) * 1000, 1)}


def build_plan(ings: list[zipingest.Ingest], query: str, run_id: str, *, budget: Budget = Budget(), tenant: str = "forge-2b", user: str = "-") -> Plan:
    """Pure, deterministic, zero model calls. Raises on malformed input; the caller decides whether that is fatal."""
    t0 = time.perf_counter()
    scope = Scope(tenant, user, run_id)
    refs = [{"name": i.filename, "kind": "zip", "files": [e.path for e in i.entries]} for i in ings]
    amap = build_attachment_map(ings, scope)
    ir = parse_request(query, refs)
    retriever = Retriever(amap)
    preview = plan_preview(ir, amap, scope, max_hits=budget.max_hits, retriever=retriever)
    dag = compile_dag(ir, amap)
    return Plan(ir, amap, scope, dag, preview, retriever, (time.perf_counter() - t0) * 1000)


def sanitized_trace(plan: Plan, mode: str) -> dict[str, Any]:
    """Trace for ``GET /v1/forge/runs/{id}``: pointers, statuses and hashes only — no file text, no prompt text."""
    goals = [{"id": g.id, "operator": g.operator, "polarity": g.polarity,
              "targets": [{"kind": t.kind, "value": t.value if t.kind in ("file", "file_group") else hashlib.sha256(t.value.encode()).hexdigest()[:12]} for t in g.targets]}
             for g in plan.ir.goals]
    nodes = []
    for e in plan.preview["preview"]:
        n = {"id": e["id"], "kind": e["kind"], "route_pref": e["route_pref"], "depends_on": e["depends_on"], "status": e.get("status")}
        if "spans" in e:
            n["spans"] = [f"{s['path']}:{s['line']}" for s in e["spans"]]
            n["spans_verified"] = all(s["verified"] for s in e["spans"])
        if "untrusted_scan" in e:
            n["untrusted"] = [f"{f['path']}:{f['line']} ({f['pattern']})" for f in e["untrusted_scan"]]
        if "typed_count" in e:
            n["typed_count"] = {"value": e["typed_count"]["value"], "method": e["typed_count"]["method"], "path": e["typed_count"]["path"]}
        if "typed_compare" in e:
            n["typed_compare"] = {"verdict": e["typed_compare"]["verdict"], "differs": [d["key"] for d in e["typed_compare"]["differs"]]}
        nodes.append(n)
    return {"version": TRACE_VERSION, "mode": mode, "status": "PLANNED", "model_calls_made": 0,
            "plan_ms": round(plan.elapsed_ms, 2), "map_id": plan.amap.map_id, "map_files": len(plan.amap.files), "map_segments": len(plan.amap.segments),
            "map_bounds_hit": plan.amap.bounds.get("hit", []),
            "ir": {"route": plan.ir.routing.route, "goals": goals, "unresolved": len(plan.ir.unresolved), "ambiguities": len(plan.ir.ambiguities),
                   "language_hint": plan.ir.language_hint},
            "dag": {"nodes": nodes, "order": plan.preview["order"], "model_calls_planned": plan.dag.model_calls_planned,
                    "exclusions": plan.dag.exclusions, "output_shape": plan.dag.output_shape},
            "preview_sha256": plan.preview["preview_sha256"]}


_LEGACY_TO_ROUTE = {"manifest": {"manifest", "housekeeping"}, "scan": {"scan"}, "overview": {"overview"}, "retrieve": {"qa", "qa_multi_source"}}


def compare_with_legacy(trace: dict[str, Any], legacy: dict[str, Any]) -> dict[str, Any]:
    """Legacy-vs-DCE differences for the shadow report. ``legacy`` = {lane, hits:[path:line], found, llm_calls, status}."""
    dce_route = trace["ir"]["route"]
    lane = legacy.get("lane") or "none"
    routes_agree = dce_route in _LEGACY_TO_ROUTE.get(lane, set())
    dce_spans: list[str] = []
    dce_statuses: list[str] = []
    for n in trace["dag"]["nodes"]:
        for s in n.get("spans", []):
            if s not in dce_spans:
                dce_spans.append(s)
        for u in n.get("untrusted", []):
            p = u.split(" (", 1)[0]
            if p not in dce_spans:
                dce_spans.append(p)
        if n.get("status"):
            dce_statuses.append(n["status"])
    lh = list(dict.fromkeys(legacy.get("hits") or []))
    a, b = set(lh), set(dce_spans)
    diffs = []
    if not routes_agree:
        diffs.append(f"route: legacy {lane} vs dce {dce_route}")
    if a != b:
        diffs.append(f"evidence: only_legacy {len(a - b)} · only_dce {len(b - a)} · shared {len(a & b)}")
    if legacy.get("found") is False and any(s == "FOUND" for s in dce_statuses):
        diffs.append("outcome: legacy not-found while dce retrieved FOUND spans")
    if "REFUSE_UNTRUSTED" in dce_statuses and lane != "scan":
        diffs.append("outcome: dce would refuse untrusted instructions; legacy did not scan")
    return {"legacy": {"lane": lane, "hits": lh, "found": legacy.get("found"), "llm_calls": legacy.get("llm_calls", 0), "status": legacy.get("status")},
            "dce": {"route": dce_route, "spans": dce_spans, "statuses": dce_statuses},
            "routes_agree": routes_agree, "evidence_jaccard": (len(a & b) / len(a | b)) if (a | b) else 1.0,
            "only_legacy": sorted(a - b), "only_dce": sorted(b - a), "differences": diffs}


# --- on-mode execution -------------------------------------------------------------------------------------------------------
@dataclass
class NodeResult:
    node_id: str
    kind: str
    goal_id: str
    route: str                        # D0 | D1 | D2
    status: str                       # NODE_STATUSES
    answer: str = ""
    spans: list[dict[str, Any]] = field(default_factory=list)   # {path, line, text, seg_id}
    detail: str = ""
    method: str = ""
    model_calls: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)


LlmCall = Callable[..., Awaitable[tuple[str, str]]]   # (messages, *, max_tokens=Q2_MAX_TOKENS) -> (content, served_model)
Q2_MAX_TOKENS = 400          # the legacy contract's completion budget
Q2_MAX_TOKENS_RETRY = 900    # second attempt after an object the token limit cut (qwen3.5 spends part of the budget on reasoning)


async def q2_decide(call_llm: LlmCall, question: str, hits: list[attach.Hit], *, max_attempts: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The existing fixed-model Q2 contract (JSON {found, answer, quotes}) with verbatim-quote verification. Unchanged schema."""
    hint: str | None = None
    json_only = False
    user_tail: str | None = None
    max_tokens = Q2_MAX_TOKENS
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_attempts + 1):
        msgs = attach.qa_messages(question, hits, retry_hint=hint, json_only=json_only, user_tail=user_tail)
        t0 = time.monotonic()
        try:
            content, served = await call_llm(msgs, max_tokens=max_tokens)
        except Exception as ex:  # noqa: BLE001 — upstream failure is recorded, never raised into the response body
            attempts.append({"attempt": attempt, "failure": f"UPSTREAM:{type(ex).__name__}"})
            hint = "upstream error"
            continue
        ms = int((time.monotonic() - t0) * 1000)
        try:
            cand = attach.parse_qa(content)
        except (ValueError, json.JSONDecodeError) as ex:
            reason = str(ex)
            attempts.append({"attempt": attempt, "failure": f"DECISION_INVALID:{reason[:60]}", "ms": ms, "max_tokens": max_tokens})
            # server log only (never the trace): the shape of what the 2B model emitted instead of the JSON object
            log.warning("dce q2 attempt %d rejected %s: served=%s chars=%d head=%r", attempt, reason[:60], served, len(content), content[:160])
            hint = reason[:80]
            # the retry must differ from the first call in what the model *sees*, or a temperature-0 model repeats itself
            # byte for byte (live 2026-11-06): prose → the JSON-only directive at the end of the user turn; an object cut
            # by the token limit → a larger completion budget. Both stay within the node's call budget (this is attempt 2).
            json_only = True   # prose, prose around a half-object, wrong shape: the directive is the one lever that changed the live answer
            if reason.startswith("truncated JSON object"):
                max_tokens = Q2_MAX_TOKENS_RETRY
            continue
        salvaged = cand.pop("salvaged", None)
        problems = attach.verify_quotes(cand, hits)
        if problems:
            attempts.append({"attempt": attempt, "failure": "QUOTE_NOT_VERBATIM", "problems": problems[:3], "ms": ms})
            hint = problems[0]
            # same lesson as above: the system-prompt hint alone left the second reply identical (live K18 2026-11-06:
            # `found: true`, `quotes: []`, twice) — the quoting directive goes at the end of the user turn
            user_tail = attach.QUOTE_TAIL
            continue
        cand["found"] = bool(cand["quotes"])
        attempts.append({"attempt": attempt, "status": "COMMITTED", "ms": ms, "served": served,
                         "prompt_sha256": hashlib.sha256(json.dumps(msgs, sort_keys=True).encode()).hexdigest(),
                         **({"salvaged": salvaged} if salvaged else {}), **({"max_tokens": max_tokens} if max_tokens != Q2_MAX_TOKENS else {})})
        return cand, attempts
    return None, attempts


# Request verbs / shape words that carry no content ("find README.md, quote its exact sentinel" → content term = sentinel).
_REQUEST_WORDS = lexicon.REQUEST_WORDS


_HEADING_RE = re.compile(r"^\s*(#{1,6}\s+\S|[A-Z][\w &/-]{0,60}:?\s*$|={3,}|-{3,})")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}(-\d{2})?\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,4}\b|\bq[1-4] \d{4}\b", re.I)
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(\.\d+)?\b")


def _is_bare_title(text: str) -> bool:
    """A line with no value signal: no digit, no key/value or list punctuation, at most four words."""
    t = text.strip()
    return bool(t) and not re.search(r"[\d:=,|\"'()\[\]{}<>]", t) and len(t.split()) <= 4


def quote_relevance_gap(plan: Plan, question: str, quoted: list[dict[str, Any]], hits: list[attach.Hit]) -> str | None:
    """Deterministic guard for a quote that is verbatim-correct but off-topic (observed live 2026-11-05: a 2B model asked to
    'find README.md, quote its exact sentinel' quoted the README title line). Returns a detail string when none of the
    quoted lines shares a content term (or its alias / typo-corrected / 5-char-stem variant) with the question while at
    least one retrieved excerpt does; None otherwise (no content terms, or the quote is on topic). Never calls a model."""
    return quote_relevance(plan, question, quoted, hits)[0]


def quote_relevance(plan: Plan, question: str, quoted: list[dict[str, Any]], hits: list[attach.Hit]) -> tuple[str | None, list[attach.Hit]]:
    """`quote_relevance_gap` plus the on-topic excerpts it found (the lines that share a content term with the question and
    were not quoted). The executor re-asks the model once over exactly those lines (`q2_on_topic_retry`)."""
    # what the user excluded ("other than the health endpoint", "but not the README") is not a content term to look for
    q = lexicon.EXCLUSION_RE.sub(" ", question)
    q = lexicon.NEGATION_RE.sub(" ", q)
    terms, expanded, typo, _anchors = plan.retriever.analyze(q)
    file_words: set[str] = set()
    for f in plan.amap.files:
        for part in re.split(r"[/.\-_]", retrieval.norm(f.path)):
            if part:
                file_words.add(part)
    content = [t for t in terms if t not in _REQUEST_WORDS and t not in file_words and not t.isdigit()]
    if not content:
        return None, []

    table = getattr(plan.retriever, "alias_table", None)

    def variants(t: str) -> list[str]:
        # `expanded` is {canonical_key: [query phrases that triggered it]}; a term inherits its key and the key's alias phrases
        keys = [k for k, phrases in expanded.items() if any(t in p.split() for p in phrases)]
        out = [t, typo.get(t, t)] + keys + [p for k in keys for p in aliases.expansions_for_key(k, table)]
        return list(dict.fromkeys(retrieval.fold(v) for v in out if v))

    def mentions(text: str, t: str) -> bool:
        ft = retrieval.fold(retrieval.norm(text))
        words = set(re.findall(r"\w+", ft))
        for v in variants(t):
            if v in ft:
                return True
            if len(v) >= 4 and any(len(w) >= 4 and (w.startswith(v[:5]) or v.startswith(w[:5])) for w in words):
                return True   # inflection: tests/test, passed/pass, released/release
        return False

    quoted_texts = [str(q.get("text", "")) for q in quoted]
    # a table header quoted for a question that names a row by its code ("item B1", "case E040"; live K25 2026-11-06:
    # `| # | item | acceptance … |` quoted, the `| B1 | … |` row was the first excerpt): the header is a label, the row
    # carrying the code is the on-topic line → re-ask over the rows that carry it
    codes = {retrieval.fold(c) for c in retrieval._CODE_RE.findall(question)} | {retrieval.fold(i) for i in retrieval._IDENT_RE.findall(question)}
    if codes and all(txt.lstrip().startswith("|") for txt in quoted_texts) and not any(c in retrieval.fold(retrieval.norm(txt)) for c in codes for txt in quoted_texts):
        rows = [h for h in hits if h.text.lstrip().startswith("|") and any(c in retrieval.fold(retrieval.norm(h.text)) for c in codes)
                and not any(h.path == q.get("path") and h.line == q.get("line") for q in quoted)]
        if rows:
            return (f"quoted table header carries none of the question's identifiers ({', '.join(sorted(codes)[:3])}); row "
                    + ", ".join(f"`{h.path}:{h.line}`" for h in rows[:3]) + " does — the quote is verbatim but is the label, not the row"), rows
    if any(mentions(txt, t) for txt in quoted_texts for t in content):
        return None, []
    # anchors (versions, identifiers, quoted strings, numbers) in the quote make it on-topic even without a shared word
    if any(retrieval.fold(a) in retrieval.fold(retrieval.norm(txt)) for a in _anchors for txt in quoted_texts):
        return None, []
    # the question names a category; the quote is an instance of it (a heading for "which section", a date for "which month")
    cset = set(content)
    if cset & {"section", "sections", "heading", "headings", "title", "chapter"} and any(_HEADING_RE.match(txt) for txt in quoted_texts):
        return None, []
    if cset & {"month", "date", "dates", "year", "day", "when", "released", "release", "time"} and any(_DATE_RE.search(txt) for txt in quoted_texts):
        return None, []
    if cset & {"version", "versions", "release", "released"} and any(_VERSION_RE.search(txt) for txt in quoted_texts):
        return None, []
    # only the observed failure mode fires: every quoted line is a bare title/heading (no values), never a content line
    if not all(_HEADING_RE.match(txt) or _is_bare_title(txt) for txt in quoted_texts):
        return None, []
    better = [h for h in hits if any(mentions(h.text, t) for t in content) and not any(h.path == q.get("path") and h.line == q.get("line") for q in quoted)]
    if not better:
        return None, []
    return (f"quoted line(s) share no term with the question ({', '.join(content[:4])}); retrieved excerpt "
            + ", ".join(f"`{h.path}:{h.line}`" for h in better[:3]) + " does — the quote is verbatim but may be off-topic, so the goal is not committed"), better


_BLOCK_SPAN_LINES = 4   # excerpt lines a multi-line (block) span may contribute: the lines that carry a question token, else its head


def _hits_from_spans(plan: Plan, entry: dict[str, Any], *, max_chars: int = 3200, question: str = "") -> list[attach.Hit]:
    """Map-verified spans → excerpt *lines* (the Q2 contract is path:line: text). A span that is a sub-line structure
    (JSON key, CSV cell) yields its whole source line; a multi-line span yields the lines that carry a question token
    (else its first lines), at most ``_BLOCK_SPAN_LINES`` — live K25 2026-11-06: one 28-line `HASHES.txt` block matched
    on the word "next" and flooded the prompt. Lines the untrusted-instruction lexicon flags are withheld from the model
    (they stay citable through the audit node, never as context)."""
    hits: list[attach.Hit] = []
    seen: set[tuple[str, int]] = set()
    total = 0
    toks = {retrieval.fold(w) for w in re.findall(r"[^\W_]+", question) if len(w) > 2 and w.casefold() not in retrieval.STOPWORDS} if question else set()
    for s in entry.get("spans", []):
        loc = plan.amap.resolve(s["seg_id"], plan.scope)          # raises if the pointer does not round-trip → node FAILED
        text = plan.amap.text_of(loc["file_id"])
        lines = text.split("\n") if text is not None else loc["text"].split("\n")
        span_lines = list(range(loc["start_line"], loc["end_line"] + 1))
        if len(span_lines) > _BLOCK_SPAN_LINES:
            def _line(ln: int) -> str:
                return lines[ln - 1] if text is not None and 0 < ln <= len(lines) else loc["text"].split("\n")[ln - loc["start_line"]]
            carrying = [ln for ln in span_lines if toks and (toks & {retrieval.fold(w) for w in re.findall(r"[^\W_]+", _line(ln))})]
            span_lines = (carrying or [ln for ln in span_lines if _line(ln).strip()])[:_BLOCK_SPAN_LINES]
        for ln in span_lines:
            line = lines[ln - 1] if text is not None and 0 < ln <= len(lines) else loc["text"].split("\n")[ln - loc["start_line"]]
            if not line.strip() or (loc["path"], ln) in seen or scan_text(line):
                continue
            seen.add((loc["path"], ln))
            total += len(line)
            if total > max_chars:
                return hits
            hits.append(attach.Hit(loc["path"], ln, line, float(s["score"])))
    return hits


_RULE_LINE_RE = re.compile(r"^\s*(?:\|?\s*:?-{2,}:?\s*)+\|?\s*$|^\s*[-=*_]{3,}\s*$")   # markdown table rules / horizontal rules


def _file_head_hits(plan: Plan, paths: list[str], *, max_lines: int = 8, max_chars: int = 3200) -> list[attach.Hit]:
    """Leading content lines of named files (headings first, then prose) as excerpts — the D2 fallback when a
    recommend/summarize goal is scoped to a file but its question carries no retrievable word ("What should we do
    next?" → `06_NEXT_RECOMMENDATION.md`; live K24 2026-11-06 failed with zero calls). Lines the untrusted lexicon
    flags are withheld, as everywhere else."""
    hits: list[attach.Hit] = []
    total = 0
    by_path = {f.path: f for f in plan.amap.files if f.status == "INCLUDED"}
    for p in paths:
        f = by_path.get(p)
        text = plan.amap.text_of(f.file_id) if f else None
        if text is None:
            continue
        lines = text.split("\n")
        picked = [ln for ln, line in enumerate(lines, 1) if line.strip() and not _RULE_LINE_RE.match(line)][:max_lines]
        for ln in picked:
            line = lines[ln - 1]
            if scan_text(line):
                continue
            total += len(line)
            if total > max_chars:
                return hits
            hits.append(attach.Hit(p, ln, line[:400], 1.0))
    return hits


def _spans_of(hits: list[attach.Hit], quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for q in quotes:
        out.append({"path": q["path"], "line": q["line"], "text": q["text"]})
    return out


def _manifest(ings: list[zipingest.Ingest]) -> str:
    return "".join(zipingest.render_manifest_markdown(i) for i in ings)


_FOLDER_MENTION_RE = re.compile(r"(?:in|inside|under|within|of|does)\s+(?:the\s+)?`?([\w./-]+?)`?\s+(?:folder|directory|dir|subfolder)\b", re.I)


def folder_inventory(ings: list[zipingest.Ingest], question: str) -> tuple[str, str] | None:
    """D0 answer for a folder question ("What is in the PUBLIC folder?"): the manifest rows under that folder, resolved
    case-insensitively against the directory components of the archive paths. Returns (method, markdown) or None when
    the question names no folder; a folder that is not in the archive gets the honest list of folders that are."""
    m = _FOLDER_MENTION_RE.search(question)
    if not m:
        return None
    want = m.group(1).strip("/").casefold()
    dirs: dict[str, str] = {}   # casefolded dir path -> as written
    for ing in ings:
        for e in ing.entries:
            parts = e.path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                d = "/".join(parts[:i])
                dirs.setdefault(d.casefold(), d)
    match = dirs.get(want) or next((d for k, d in dirs.items() if k.endswith("/" + want) or k.split("/")[-1] == want), None)
    if match is None:
        top = sorted({d for d in dirs.values() if "/" not in d})
        return "manifest_folder", (f"**Not found in the attached archive(s)** — no folder named `{m.group(1)}`. Top-level folders: "
                                   + (", ".join(f"`{d}/`" for d in top) if top else "none (all files are at the archive root)") + ".")
    rows = ["| # | path | status | bytes | lines | type | note |", "|---|---|---|---|---|---|---|"]
    n = 0
    for ing in ings:
        for e in ing.entries:
            if e.path == match or e.path.startswith(match + "/"):
                n += 1
                rows.append(f"| {n} | `{e.path}` | {e.status} | {e.bytes} | {e.lines or ''} | {e.mime} | {e.skip_reason or ing.integrity.get(e.path, '')} |")
    sub = sorted({d for d in dirs.values() if d.startswith(match + "/") and d.count("/") == match.count("/") + 1})
    head = f"**Folder** `{match}/` · {n} file(s)" + (f" · subfolders: " + ", ".join(f"`{d.split('/')[-1]}/`" for d in sub) if sub else "") + "\n\n"
    return "manifest_folder", head + "\n".join(rows) + "\n"


def _structure(plan: Plan) -> str:
    rows = []
    for f in plan.amap.files:
        if f.status != "INCLUDED":
            continue
        segs = plan.amap.segments_for(f.file_id)
        kinds: dict[str, int] = {}
        for s in segs:
            kinds[s.kind] = kinds.get(s.kind, 0) + 1
        rows.append(f"| `{f.path}` | {f.language} | {'/'.join(f.role_hints) or '—'} | {f.lines} | " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) + " |")
    return "| file | language | role | lines | segments |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n"


def _anchor_of(entry: dict[str, Any]) -> str:
    cov = entry.get("coverage") or {}
    missing = cov.get("missing") or cov.get("anchors_missing") or []
    return ", ".join(f"'{m}'" for m in missing[:3]) if isinstance(missing, list) and missing else "the requested literal"


async def execute(plan: Plan, ings: list[zipingest.Ingest], call_llm: LlmCall | None, budget: Budget,
                  on_node: Callable[[NodeResult], Awaitable[None]] | None = None) -> list[NodeResult]:
    """Run the DAG in topological order. Model calls are capped by ``budget.max_model_calls``; D2 nodes reuse spans already
    verified by the nodes they depend on. Never raises for per-node failures — they become FAILED results."""
    by_id = {e["id"]: e for e in plan.preview["preview"]}
    nodes = {n.id: n for n in plan.dag.nodes}
    results: dict[str, NodeResult] = {}
    calls_used = 0
    for nid in plan.dag.topological_order():
        n, e = nodes[nid], by_id[nid]
        r = NodeResult(nid, n.kind, n.goal_id, e.get("route_pref", n.route_pref), "FAILED")
        try:
            if n.kind == "inventory":
                folder = folder_inventory(ings, n.query) if n.goal_id and n.query else None
                r.route, r.status = "D0", "COMMITTED"
                r.method, r.answer = folder if folder else ("manifest", _manifest(ings))
            elif n.kind == "parse_structure":
                r.route, r.status, r.method, r.answer = "D0", "COMMITTED", "attachment_map", _structure(plan)
            elif "untrusted_scan" in e:
                findings = [Finding(**f) for f in e["untrusted_scan"]]
                r.route, r.status, r.method = "D0", "COMMITTED", "instruction_lexicon_scan"
                r.spans = [{"path": f.path, "line": f.line, "text": f.text, "seg_id": f.seg_id} for f in findings]
                r.answer = refusal_text(findings) if findings else (f"No instruction-like text was found in the {sum(1 for f in plan.amap.files if f.status == 'INCLUDED')} readable file(s) "
                                                                   "(deterministic lexicon scan; file contents were not interpreted).")
                r.detail = "REFUSE_UNTRUSTED" if findings else "CLEAN"
            elif n.failure.startswith("negated goal"):
                r.route, r.status, r.method, r.answer = "D0", "COMMITTED", "negation", "Not performed (the request says not to)."
            elif "typed_count" in e:
                tc = e["typed_count"]
                r.route, r.status, r.method = "D0", "COMMITTED", tc["method"]
                if tc["method"].startswith("manifest_count"):
                    r.answer = (f"**{tc['value']}** {tc['method'].split(':')[1]} in the attached archive(s)" + (f" — {tc['detail']}" if tc.get("detail") else "")
                                + " (counted from the archive manifest; no file content was read and no model was called).")
                else:
                    r.answer = f"**{tc['value']}** ({tc['method'].replace(':', ': ')}) in `{tc['path']}`"
                for seg_id, line in zip(tc["spans"], tc["lines"]):
                    loc = plan.amap.resolve(seg_id, plan.scope)
                    r.spans.append({"path": loc["path"], "line": line, "text": loc["text"].split("\n")[0][:200], "seg_id": seg_id})
            elif "typed_compare" in e:
                td = e["typed_compare"]
                r.route, r.status, r.method = "D0", "COMMITTED", td["method"]
                lines = [f"- `{d['key']}`: " + " vs ".join(f"`{s['value']}` (`{s['path']}:{s['line']}`)" for s in d["sides"]) for d in td["differs"]]
                only = [f"- `{k}` only in `{p}`" for p, ks in td["only_in"].items() for k in ks]
                r.answer = (f"Verdict: **{td['verdict']}** — {len(td['differs'])} differing key(s), {len(td['same'])} identical.\n" + "\n".join(lines + only)).strip()
                for d in td["differs"]:
                    for s in d["sides"]:
                        loc = plan.amap.resolve(s["seg_id"], plan.scope)
                        r.spans.append({"path": s["path"], "line": s["line"], "text": loc["text"].split("\n")[0][:200], "seg_id": s["seg_id"]})
            elif "typed_dated_sections" in e:
                # D0: dated/versioned headings ordered from the map; the selector picks the entry, its body lines come along
                ts = e["typed_dated_sections"]
                r.route, r.status, r.method = "D0", "COMMITTED", ts["method"]
                picked = [ts["entries"][i] for i in ts["chosen"]] if ts["chosen"] else ts["entries"]
                if ts["chosen"]:
                    parts = []
                    for en in picked:
                        parts.append(f"**{en['text'].lstrip('# ').strip()}** (`{ts['path']}:{en['line']}`, {ts['ordered_by']} {en['key']})"
                                     + "".join(f"\n  {b['text'].strip()} (`{ts['path']}:{b['line']}`)" for b in en["body"]))
                    r.answer = "\n".join(parts) + (f"\n_{ts['note']}_" if ts["note"] else "")
                else:
                    r.answer = (f"{len(ts['entries'])} dated entries in `{ts['path']}` ({ts['ordered_by']} order, newest first) — {ts['note']}:\n"
                                + "\n".join(f"- {en['text'].lstrip('# ').strip()} (`{ts['path']}:{en['line']}`)" for en in ts["entries"]))
                    r.detail = ts["note"]
                for en in picked:
                    for sp in [en] + (en["body"] if ts["chosen"] else []):
                        loc = plan.amap.resolve(sp["seg_id"], plan.scope)
                        r.spans.append({"path": ts["path"], "line": sp["line"], "text": loc["text"].split("\n")[0][:200], "seg_id": sp["seg_id"]})
            elif "typed_key_lookup" in e:
                # D0: the best-ranked line *is* the asked config key — read the value from the map, no model call
                tk = e["typed_key_lookup"]
                r.route, r.status, r.method = "D0", "COMMITTED", tk["method"]
                vals = tk["values"]
                if len(vals) == 1 and not tk["ambiguous"]:
                    r.answer = f"`{tk['key']}` = **{vals[0]['value']}** (`{vals[0]['path']}:{vals[0]['line']}`)" + (f" — {tk['note']}" if tk["note"] else "")
                else:
                    r.answer = (f"`{tk['key']}` has {len(vals)} values in the attached files — the question does not say which file, so none is chosen:\n"
                                + "\n".join(f"- **{v['value']}** (`{v['path']}:{v['line']}`)" for v in vals))
                    r.detail = tk["note"]
                if tk.get("corroborating"):
                    r.answer += "\n" + "Also stated in: " + ", ".join(f"`{c['path']}:{c['line']}`" for c in tk["corroborating"])
                for v in vals + tk.get("corroborating", []):
                    loc = plan.amap.resolve(v["seg_id"], plan.scope)
                    r.spans.append({"path": v["path"], "line": v["line"], "text": loc["text"].split("\n")[0][:200], "seg_id": v["seg_id"]})
            elif n.kind in ("summarize", "recommend"):
                # D2: one bounded Q2 call over spans already verified by the nodes it depends on (fallback: its own retrieval)
                deps_spans = [s for d in n.depends_on for s in results.get(d, NodeResult("", "", "", "", "")).spans if results.get(d) and results[d].status == "COMMITTED"]
                hits = [attach.Hit(s["path"], s["line"], s["text"], 1.0) for s in deps_spans][:8] or (_hits_from_spans(plan, e, question=n.query) if e.get("status") == "FOUND" else [])
                named = list(n.source_scope.get("files") or n.source_scope.get("focus") or [])   # hard scope, else the inferred file
                if not hits and named:
                    hits = _file_head_hits(plan, named)   # the named file's leading lines (deterministic, bounded)
                    r.method = "file_head_lines" if hits else ""
                if not hits and n.kind == "summarize":
                    hits = [h for h in attach.overview_hits(ings) if not scan_text(h.text)]   # headline line per file, as the legacy overview
                    r.method = "overview_lines"
                r.route = "D2"
                if not hits:
                    r.status, r.detail = "FAILED", n.failure
                elif call_llm is None or calls_used >= budget.max_model_calls:
                    r.status, r.detail = "SKIPPED", f"model-call budget exhausted ({calls_used}/{budget.max_model_calls})"
                else:
                    q = ("Based only on these excerpts, " + n.query.strip().rstrip(".") + ". Quote the excerpt lines your answer rests on.")
                    dec, r.attempts = await q2_decide(call_llm, q, hits, max_attempts=budget.max_attempts)
                    calls_used += len(r.attempts)
                    r.model_calls = len(r.attempts)
                    if dec is None:
                        r.status, r.detail = "FAILED", "no verifiable model output"
                    else:
                        r.status, r.method = "PARTIAL", "q2_over_" + (r.method or "verified_spans")
                        r.answer, r.spans = dec["answer"], _spans_of(hits, dec["quotes"])
                        r.detail = "quotes verified verbatim; the reasoning itself is model output and is not deterministically entailed"
            elif _SIDE_RE.search(nid):
                # compare side: evidence gathering only (verified pointers), the single model call happens in the compare node
                r.route = "D1"
                if e.get("status") == "FOUND" and e.get("spans"):
                    r.status, r.method = "COMMITTED", "retrieval_verified_spans"
                    r.spans = [{"path": h.path, "line": h.line, "text": h.text, "seg_id": ""} for h in _hits_from_spans(plan, e, question=n.query)]
                else:
                    r.status, r.detail = "FAILED", n.failure
            elif n.kind == "compare" and any(_SIDE_RE.search(d) for d in n.depends_on):
                sides = [results[d] for d in n.depends_on if _SIDE_RE.search(d)]
                r.route = "D1"
                if any(s.status != "COMMITTED" for s in sides):
                    r.status, r.detail = "FAILED", n.failure
                elif call_llm is None or calls_used >= budget.max_model_calls:
                    r.status, r.detail = "SKIPPED", f"model-call budget exhausted ({calls_used}/{budget.max_model_calls})"
                else:
                    # round-robin across sides so a quote-capped model sees every side early
                    hits: list[attach.Hit] = []
                    for i in range(max(len(s.spans) for s in sides)):
                        for side in sides:
                            if i < len(side.spans):
                                hits.append(attach.Hit(side.spans[i]["path"], side.spans[i]["line"], side.spans[i]["text"], 1.0))
                    hits = hits[:8]
                    dec, r.attempts = await q2_decide(call_llm, n.query, hits, max_attempts=budget.max_attempts)
                    calls_used += len(r.attempts)
                    r.model_calls = len(r.attempts)
                    if dec is None or not dec["quotes"]:
                        r.status, r.detail = "FAILED", "no verified quotes from both sides; verdict undetermined (never guessed)"
                    else:
                        quotes = list(dec["quotes"])
                        cited = {q["path"] for q in quotes}
                        missing = [side for side in sides if not any(s["path"] in cited for s in side.spans)]
                        if missing and calls_used < budget.max_model_calls:
                            # one bounded complement call over the unquoted side(s) only (live finding 2026-11-05: the 2B model
                            # quotes a single side even when every side is in its excerpts)
                            other = [attach.Hit(s["path"], s["line"], s["text"], 1.0) for side in missing for s in side.spans][:8]
                            dec2, att2 = await q2_decide(call_llm, n.query, other, max_attempts=1)
                            calls_used += len(att2)
                            r.model_calls += len(att2)
                            r.attempts = r.attempts + att2
                            if dec2 and dec2["quotes"]:
                                quotes += dec2["quotes"]
                                cited = {q["path"] for q in quotes}
                        both = all(any(s["path"] in cited for s in side.spans) for side in sides)
                        r.status = "COMMITTED" if both else "PARTIAL"
                        r.method, r.answer, r.spans = "q2_verified_quotes", dec["answer"], _spans_of(hits, quotes)
                        r.detail = ("second side quoted in a complement call" if both and len(r.attempts) > 1 else "") if both else "only one side is quoted; the other side is unverified"
            else:
                status = e.get("status")
                if status == "NOT_FOUND":
                    r.route, r.status, r.method = "D0", "COMMITTED", "exhaustive_literal_scan"
                    r.answer = (f"**Not found in the attached archive(s).** {_anchor_of(e)} does not occur in any readable attached file "
                                f"({sum(1 for f in plan.amap.files if f.status == 'INCLUDED')} file(s) scanned literally; nothing was sent to the model).")
                elif status == "SOURCE_UNREADABLE":
                    r.status, r.detail = "FAILED", "the file(s) in scope are unreadable (skipped, binary or integrity failure)"
                elif status != "FOUND" or not e.get("spans"):
                    # honest negative, distinct from NOT_FOUND: nothing in the map matched, so nothing went to the model
                    r.route, r.status, r.method = "D0", "COMMITTED", "not_retrieved"
                    r.answer = (f"**Not found in the attached archive(s)** — no evidence retrieved: no line in the {sum(1 for f in plan.amap.files if f.status == 'INCLUDED')} readable attached file(s) "
                                "matches this question (deterministic retrieval; nothing was sent to the model). This is *not retrieved*, not proof of absence — "
                                "name the file or the exact term to narrow it.")
                    r.detail = "NOT_RETRIEVED"
                elif call_llm is None or calls_used >= budget.max_model_calls:
                    r.status, r.detail = "SKIPPED", f"model-call budget exhausted ({calls_used}/{budget.max_model_calls})"
                    r.spans = [{"path": s["path"], "line": s["line"], "text": "", "seg_id": s["seg_id"]} for s in e["spans"]]
                else:
                    hits = _hits_from_spans(plan, e, question=n.query)
                    r.route = "D1"
                    dec, r.attempts = await q2_decide(call_llm, n.query, hits, max_attempts=budget.max_attempts)
                    calls_used += len(r.attempts)
                    r.model_calls = len(r.attempts)
                    if dec is None:
                        r.status, r.detail = "FAILED", f"{len(r.attempts)} attempt(s) rejected: " + str(r.attempts[-1].get("failure") if r.attempts else "none")
                    elif not dec["quotes"]:
                        # the legacy contract's honest negative: excerpts were verified, the model found no answer in them
                        r.status, r.method, r.detail = "COMMITTED", "q2_not_in_excerpts", "NOT_FOUND_IN_EXCERPTS"
                        r.answer = (f"**Not found in the attached archive(s)** — not in the {len(hits)} retrieved excerpt(s): the model reported no answer there and quoted nothing, so no claim is made."
                                    + (f" Model note: {dec['answer']}" if dec.get("answer") else ""))
                        r.spans = [{"path": h.path, "line": h.line, "text": "", "seg_id": ""} for h in hits[:8]]
                    else:
                        r.status, r.method, r.answer, r.spans = "COMMITTED", "q2_verified_quotes", dec["answer"], _spans_of(hits, dec["quotes"])
                        gap, on_topic = quote_relevance(plan, n.query, dec["quotes"], hits)
                        if gap:
                            # the model quoted a bare title although an excerpt sharing the question's term was in front of it
                            # (live 2026-11-05/06, Granite `on`: "quote its exact sentinel" → the README title). One bounded
                            # re-ask over *only* the on-topic excerpts; its quote is verified verbatim like any other, and the
                            # off-topic first quote is dropped. No usable second quote → PARTIAL with the guard's explanation.
                            dec2, att2 = (None, [])
                            if on_topic and calls_used < budget.max_model_calls:
                                dec2, att2 = await q2_decide(call_llm, n.query, on_topic[:8], max_attempts=1)
                                calls_used += len(att2)
                                r.model_calls += len(att2)
                                r.attempts = r.attempts + att2
                            if dec2 and dec2["quotes"] and not quote_relevance_gap(plan, n.query, dec2["quotes"], on_topic):
                                r.method, r.answer, r.spans = "q2_on_topic_retry", dec2["answer"], _spans_of(hits, dec2["quotes"])
                                r.detail = "first quote was an off-topic title; re-asked over the on-topic excerpt(s) only"
                            else:
                                r.status, r.detail = "PARTIAL", gap
                        elif n.kind == "compare" and len({(q["path"], q["line"]) for q in dec["quotes"]}) < 2:
                            # a comparison with one quoted side is a guess about the other (live finding 2026-11-05: "Yes" citing
                            # example.py only). One bounded complement call over the *remaining* excerpts asks for the other side;
                            # the verdict stays the first answer's, now resting on two verified lines — otherwise PARTIAL.
                            quoted = {(q["path"], q["line"]) for q in dec["quotes"]}
                            other = [h for h in hits if (h.path, h.line) not in quoted]
                            dec2, att2 = (None, [])
                            if other and calls_used < budget.max_model_calls:
                                dec2, att2 = await q2_decide(call_llm, n.query, other[:8], max_attempts=1)
                                calls_used += len(att2)
                                r.model_calls += len(att2)
                                r.attempts = r.attempts + att2
                            if dec2 and dec2["quotes"]:
                                r.spans = _spans_of(hits, dec["quotes"] + dec2["quotes"])
                                r.detail = "second side quoted in a complement call over the remaining excerpts"
                            else:
                                r.status, r.detail = "PARTIAL", "compare: only one side is quoted; the verdict is not committed"
        except Exception as ex:  # noqa: BLE001 — a broken pointer or parser edge case fails the node, never the process
            r.status, r.detail = "FAILED", f"{type(ex).__name__}: {str(ex)[:120]}"
        results[nid] = r
        if on_node is not None:
            await on_node(r)
    return [results[i] for i in plan.dag.topological_order()]


def merge_gate(plan: Plan, results: list[NodeResult]) -> dict[str, Any]:
    """Every goal must be covered by a COMMITTED node (or PARTIAL for D2), every cited span must round-trip through the map.
    No committed run while a goal is unverified."""
    by_goal: dict[str, list[NodeResult]] = {}
    for r in results:
        if r.goal_id:
            by_goal.setdefault(r.goal_id, []).append(r)
    goals = []
    for g in plan.ir.goals:
        rs = by_goal.get(g.id, [])
        final = [r for r in rs if r.node_id == f"{g.id}_{r.kind}"] or rs
        st = "UNSUPPORTED"
        if final:
            sts = {r.status for r in final}
            st = "COMMITTED" if sts == {"COMMITTED"} else "PARTIAL" if "COMMITTED" in sts or "PARTIAL" in sts else "SKIPPED" if sts == {"SKIPPED"} else "FAILED" if "FAILED" in sts else "UNSUPPORTED"
        goals.append({"goal_id": g.id, "operator": g.operator, "text": g.span.text, "status": st, "nodes": [r.node_id for r in rs]})
    span_problems = []
    for r in results:
        for s in r.spans:
            if s.get("seg_id") and s["seg_id"] in plan.amap._segs:
                try:
                    plan.amap.resolve(s["seg_id"], plan.scope)
                except Exception as ex:  # noqa: BLE001
                    span_problems.append(f"{r.node_id}: {s['seg_id']} {type(ex).__name__}")
            elif not plan.amap.locate(s["path"], s["line"], plan.scope):
                span_problems.append(f"{r.node_id}: {s['path']}:{s['line']} not in map")
    unresolved = [{"text": u.span.text, "reason": u.reason} for u in plan.ir.unresolved]
    statuses = [g["status"] for g in goals]
    if not goals:
        status = "COMMITTED" if all(r.status == "COMMITTED" for r in results) else "PARTIAL"
    elif span_problems or all(s in ("FAILED", "UNSUPPORTED", "SKIPPED") for s in statuses):
        status = "FAILED"
    elif all(s == "COMMITTED" for s in statuses) and not unresolved:
        status = "COMMITTED"
    else:
        status = "PARTIAL"
    return {"status": status, "goals": goals, "span_problems": span_problems, "unresolved": unresolved,
            "model_calls_made": sum(r.model_calls for r in results), "nodes": {r.node_id: r.status for r in results}}


def render(run_id: str, plan: Plan, results: list[NodeResult], gate: dict[str, Any], *, backend_model: str) -> str:
    out = [f"**forge-2b DCE lane** · run `{run_id}` · mode `on` · backend `{backend_model}` · {gate['model_calls_made']} model call(s)  \n"
           "Deterministic (D0) nodes answer from the verified attachment map; D1/D2 nodes send only map-verified excerpts to the fixed model and every "
           "quote is checked verbatim. Status: **" + gate["status"] + "**.\n"]
    goal_text = {g.id: g for g in plan.ir.goals}
    wants_list = any(g.operator == "list" for g in plan.ir.goals) or not plan.ir.goals
    wants_structure = any(g.operator == "inspect" and len(g.span.text.split()) <= 4 for g in plan.ir.goals)
    for r in results:
        if r.kind == "inventory" and not r.goal_id:
            if wants_list:
                out.append("\n**Files (manifest, D0):**\n\n" + r.answer)
            continue
        if r.kind == "parse_structure" and not r.goal_id:
            if wants_structure:
                out.append("\n**Structure (attachment map, D0):**\n\n" + r.answer)
            continue
        if not r.goal_id or r.node_id != f"{r.goal_id}_{r.kind}":
            continue   # compare side-lookups are folded into their compare node
        g = goal_text.get(r.goal_id)
        label = {"COMMITTED": "✓", "PARTIAL": "◐", "FAILED": "✗", "UNSUPPORTED": "⊘", "SKIPPED": "…"}[r.status]
        out.append(f"\n### {label} {g.operator if g else r.kind}: {g.span.text if g else r.node_id}\n")
        out.append(f"_{r.route} · {r.method or r.kind} · {r.status}_" + (f" — {r.detail}" if r.detail and r.status != "COMMITTED" else "") + "\n\n")
        if r.answer:
            out.append(r.answer.rstrip() + "\n")
        if r.spans and r.method not in ("manifest", "attachment_map"):
            out.append("\n**Excerpts checked (no answer in them):**\n" if r.method == "q2_not_in_excerpts" else "\n**Evidence:**\n")
            for s in r.spans[:12]:
                txt = s.get("text") or ""
                out.append(f"- `{s['path']}:{s['line']}`" + (f" — {txt[:200]}" if txt else "") + "\n")
        if r.attempts:
            out.append(f"\n_{len(r.attempts)} model attempt(s); prompt sha `{r.attempts[-1].get('prompt_sha256', '')[:12]}`_\n")
    out.append("\n**Coverage gate:**\n\n| goal | operator | status |\n|---|---|---|\n")
    for g in gate["goals"]:
        out.append(f"| {g['text'][:80].replace('|', '\\|')} | {g['operator']} | {g['status']} |\n")
    if gate["unresolved"]:
        out.append("\nUnresolved request parts (not acted on): " + "; ".join(f"“{u['text'][:60]}” ({u['reason']})" for u in gate["unresolved"]) + "\n")
    if gate["span_problems"]:
        out.append("\nSpan verification problems: " + "; ".join(gate["span_problems"][:5]) + "\n")
    if gate["status"] != "COMMITTED":
        out.append(f"\n_Run {gate['status']}: goals not marked COMMITTED were not answered with verified evidence; nothing was guessed._\n")
    return "".join(out)


def results_trace(results: list[NodeResult]) -> list[dict[str, Any]]:
    out = []
    for r in results:
        d = asdict(r)
        d["spans"] = [f"{s['path']}:{s['line']}" for s in r.spans]
        d["answer_sha256"] = hashlib.sha256(r.answer.encode()).hexdigest()[:16]
        d.pop("answer")
        out.append(d)
    return out


_SIDE_RE = re.compile(r"_lookup_\d+$")
