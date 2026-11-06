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

Module layout (Phase 3 refactor, no behaviour change):
  shadow.py      — modes, budget, the deterministic plan stage, the sanitized trace, the ``execute`` dispatcher and the merge gate
  escalation.py  — the Q2 contract, the deterministic guards and the D1 / D2 / compare node runners (every model call)
  render.py      — D0 answer text read from the map and the final run markdown
Every public name the facade, scripts and tests used from ``shadow`` is re-exported here.

The 10-K lane and the SOURCE/END_SOURCE fixture are not touched by any mode. Everything here is bounded: one semaphore,
a wall-clock budget for the deterministic stage, and a per-run model-call cap. Nothing in this module performs I/O.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .. import zipingest
from .attachment_map import AttachmentMap, Scope, build_attachment_map, warm_parse_cache
from .dag import TaskDAG, compile_dag, plan_preview
from .ir import RequestIR
from .parse import parse_request
from .retrieval import Retriever
from .untrusted import Finding, refusal_text
from . import escalation, render as _render
from .escalation import (  # noqa: F401 — re-exported API (facade, scripts, tests)
    LlmCall, Q2_MAX_TOKENS, Q2_MAX_TOKENS_RETRY, _BLOCK_SPAN_LINES, _HEADING_RE, _content_terms, _is_bare_title,
    covering_excerpts, numbers_not_in_quotes, q2_decide, quote_relevance, quote_relevance_gap,
)
from .render import folder_inventory, results_trace  # noqa: F401 — re-exported API

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
    plan_ms: float = 3000.0       # deterministic stage (parse + map + DAG + dry-run retrieval) wall-clock cap; warm plan 0.45 s median, 1.5 s tail on a 68-file package
    max_hits: int = 8
    max_model_calls: int = 3      # per run, all D1/D2 nodes together
    max_attempts: int = 2         # per node, same as the legacy Q2 loop
    # D2 sentence entailment (decision 2, 2026-11-06): `lenient` = every D2 node PARTIAL as before, unentailed sentences only
    # counted in the trace; `strict` = unentailed sentences removed and listed, all-entailed → COMMITTED; `off` = no check.
    # Read from FORGE_2B_DCE_D2 here (not facade.Config) while facade.py carries another chat's uncommitted work.
    d2_mode: str = field(default_factory=lambda: d2_mode_from_env())


def d2_mode_from_env() -> str:
    v = (os.environ.get("FORGE_2B_DCE_D2") or "lenient").strip().lower()
    return v if v in ("strict", "lenient", "off") else "lenient"


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
        if "typed_table" in e:
            tt = e["typed_table"]
            n["typed_table"] = {"method": tt["method"], **({"label": tt.get("label", ""), "rows": len(tt["entries"])} if "entries" in tt else {}),
                                **({"column": tt["column"], "label": tt["label"]} if tt["method"] == "typed_table_extreme" else {}),
                                **({"files": len(tt["files"])} if "files" in tt else {}),
                                **({"commits": len(tt["commits"]), "path": tt["path"]} if "commits" in tt else {})}
        if "typed_verdict" in e:
            tv = e["typed_verdict"]
            n["typed_verdict"] = {"value": tv["value"], "statements": len(tv["entries"])}
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


# compatibility aliases — the excerpt builders moved to ``escalation`` under public names
_hits_from_spans = escalation.hits_from_spans
_file_head_hits = escalation.file_head_hits
_spans_of = escalation.spans_of
_SIDE_RE = re.compile(r"_lookup_\d+$")


async def execute(plan: Plan, ings: list[zipingest.Ingest], call_llm: LlmCall | None, budget: Budget,
                  on_node: Callable[[NodeResult], Awaitable[None]] | None = None) -> list[NodeResult]:
    """Run the DAG in topological order. Model calls are capped by ``budget.max_model_calls``; D2 nodes reuse spans already
    verified by the nodes they depend on. Never raises for per-node failures — they become FAILED results.
    D0 answers are rendered by ``render``; every node that reaches the model runs through ``escalation``."""
    by_id = {e["id"]: e for e in plan.preview["preview"]}
    nodes = {n.id: n for n in plan.dag.nodes}
    results: dict[str, NodeResult] = {}
    calls = escalation.Calls(cap=budget.max_model_calls)
    for nid in plan.dag.topological_order():
        n, e = nodes[nid], by_id[nid]
        r = NodeResult(nid, n.kind, n.goal_id, e.get("route_pref", n.route_pref), "FAILED")
        try:
            if n.kind == "inventory":
                folder = folder_inventory(ings, n.query) if n.goal_id and n.query else None
                r.route, r.status = "D0", "COMMITTED"
                r.method, r.answer = folder if folder else ("manifest", _render.manifest(ings))
            elif n.kind == "parse_structure":
                r.route, r.status, r.method, r.answer = "D0", "COMMITTED", "attachment_map", _render.structure(plan)
            elif "untrusted_scan" in e:
                findings = [Finding(**f) for f in e["untrusted_scan"]]
                r.route, r.status, r.method = "D0", "COMMITTED", "instruction_lexicon_scan"
                r.spans = [{"path": f.path, "line": f.line, "text": f.text, "seg_id": f.seg_id} for f in findings]
                r.answer = refusal_text(findings) if findings else (f"No instruction-like text was found in the {_render.readable_files(plan)} readable file(s) "
                                                                   "(deterministic lexicon scan; file contents were not interpreted).")
                r.detail = "REFUSE_UNTRUSTED" if findings else "CLEAN"
            elif n.failure.startswith("negated goal"):
                r.route, r.status, r.method, r.answer = "D0", "COMMITTED", "negation", "Not performed (the request says not to)."
            elif "typed_count" in e:
                r.route, r.status = "D0", "COMMITTED"
                _render.typed_count(r, e["typed_count"], plan)
            elif "typed_compare" in e:
                r.route, r.status = "D0", "COMMITTED"
                _render.typed_compare(r, e["typed_compare"], plan)
            elif "typed_dated_sections" in e:
                r.route, r.status = "D0", "COMMITTED"
                _render.typed_dated_sections(r, e["typed_dated_sections"], plan)
            elif "typed_table" in e:
                r.route, r.status = "D0", "COMMITTED"
                _render.typed_table(r, e["typed_table"], plan)
            elif "typed_verdict" in e:
                r.route, r.status = "D0", "COMMITTED"
                _render.typed_verdict(r, e["typed_verdict"], plan)
            elif "typed_key_lookup" in e:
                r.route, r.status = "D0", "COMMITTED"
                _render.typed_key_lookup(r, e["typed_key_lookup"], plan)
            elif n.kind in ("summarize", "recommend"):
                await escalation.run_d2(r, n, e, plan, ings, results, call_llm, budget, calls)
            elif _SIDE_RE.search(nid):
                # compare side: evidence gathering only (verified pointers), the single model call happens in the compare node
                r.route = "D1"
                if e.get("status") == "FOUND" and e.get("spans"):
                    r.status, r.method = "COMMITTED", "retrieval_verified_spans"
                    r.spans = [{"path": h.path, "line": h.line, "text": h.text, "seg_id": ""} for h in escalation.hits_from_spans(plan, e, question=n.query)]
                else:
                    r.status, r.detail = "FAILED", n.failure
            elif n.kind == "compare" and any(_SIDE_RE.search(d) for d in n.depends_on):
                sides = [results[d] for d in n.depends_on if _SIDE_RE.search(d)]
                await escalation.run_compare_sides(r, n, sides, call_llm, budget, calls)
            else:
                status = e.get("status")
                if status == "NOT_FOUND":
                    r.route, r.status, r.method = "D0", "COMMITTED", "exhaustive_literal_scan"
                    r.answer = (f"**Not found in the attached archive(s).** {_render.anchor_of(e)} does not occur in any readable attached file "
                                f"({_render.readable_files(plan)} file(s) scanned literally; nothing was sent to the model).")
                elif status == "SOURCE_UNREADABLE":
                    r.status, r.detail = "FAILED", "the file(s) in scope are unreadable (skipped, binary or integrity failure)"
                elif status != "FOUND" or not e.get("spans"):
                    # honest negative, distinct from NOT_FOUND: nothing in the map matched, so nothing went to the model
                    r.route, r.status, r.method = "D0", "COMMITTED", "not_retrieved"
                    r.answer = (f"**Not found in the attached archive(s)** — no evidence retrieved: no line in the {_render.readable_files(plan)} readable attached file(s) "
                                "matches this question (deterministic retrieval; nothing was sent to the model). This is *not retrieved*, not proof of absence — "
                                "name the file or the exact term to narrow it.")
                    r.detail = "NOT_RETRIEVED"
                else:
                    await escalation.run_d1(r, n, e, plan, call_llm, budget, calls)
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
    """The user-visible run markdown (see ``render.run_markdown``)."""
    return _render.run_markdown(run_id, plan, results, gate, backend_model=backend_model)
