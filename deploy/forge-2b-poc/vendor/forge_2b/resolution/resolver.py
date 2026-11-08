"""DCE-G3 — orchestrator: selection → bounded requests → backend → verifier → ResolutionOverlay (+ debug trace).

``resolve`` is a pure function of (RequestIR, utterance, EvidenceGraph, sources_text, backend, budget): it never mutates its
inputs (asserted by digest before/after), never touches the network itself (the backend does, if it is a live one), never
decides anything. With ``backend=None`` it performs selection only and makes zero calls.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from forge_2b.request_ir import schema as S
from forge_2b.request_ir.evidence_graph import EvidenceGraph

from . import prompts
from .backends import BackendError, BackendResult, ResolverBackend, prompt_digest
from .contracts import (NOTES, REQUEST_SCHEMA_VERSION, RESOLUTION_SCHEMA_VERSION, RESOLVER_VERSION, VERIFIER_VERSION, Budget,
                        RequestSpan, ResolutionOverlay, ResolutionRequest, VerifierFinding, digest_of, validate_request)
from .selection import Selection, SelectedNode, candidates_for, clause_context, select
from .verifier import VerifyResult, verify


def ir_digest(ir: S.RequestIR) -> str:
    return digest_of(ir.to_dict())


@dataclass
class TraceEntry:
    index: int
    path: str
    node_id: Optional[str]
    uncertainty_reason: str
    rule_id: str
    candidate_refs: list[str]
    prompt_digest: str
    estimated_input_tokens: int
    backend_kind: str
    model_id: str
    input_tokens: int
    output_tokens: int
    model_ms: float
    verifier_ms: float
    attempts: int
    disposition: str
    rule_ids: list[str]


@dataclass
class ResolveResult:
    overlay: ResolutionOverlay
    trace: list[TraceEntry] = field(default_factory=list)

    def trace_dicts(self) -> list[dict[str, Any]]:
        return [t.__dict__ for t in self.trace]


def _node_summaries(ir: S.RequestIR) -> list[str]:
    g = ir.graph
    out = [f"{o.id} objective[{o.action}] {o.text!r}" for o in g.objectives]
    out += [f"{c.id} constraint[{c.kind}] {c.text!r}" for c in g.constraints]
    out += [f"{q.id} condition[{q.kind}] {q.text!r}" for q in g.conditions]
    out += [f"{u.id} unresolved[{u.kind}] {u.text!r}" for u in g.unresolved]
    out += [f"{k.id} context {k.text!r}" for k in g.context_statements]
    return out


def _call(backend: ResolverBackend, prompt: str, budget: Budget, seed: int, remaining: int) -> tuple[Optional[BackendResult], Optional[str], int]:
    """<= ``budget.retries`` retries, only on transport failure or empty text, and never more attempts than ``remaining``
    (the hard ``max_total_calls`` allowance left — review F11: the cap counts actual backend invocations, retries included)."""
    attempts, last_err = 0, None
    while attempts <= budget.retries and attempts < remaining:
        attempts += 1
        try:
            r = backend.complete(prompt, max_tokens=budget.max_output_tokens, seed=seed)
            if r.text.strip():
                return r, None, attempts
            last_err = "empty model output"
        except BackendError as ex:
            last_err = str(ex)
    if attempts == 0:
        last_err = "total call budget exhausted before the first attempt"
    elif attempts <= budget.retries and last_err is not None:
        last_err += " (no retry: total call budget exhausted)"
    return None, last_err, attempts


def resolve(ir: S.RequestIR, utterance: str, graph: Optional[EvidenceGraph], *, backend: Optional[ResolverBackend],
            sources_text: Optional[dict[str, str]] = None, budget: Budget = Budget(), seed: int = 0) -> ResolveResult:
    if not isinstance(ir, S.RequestIR):
        raise TypeError("ir must be a RequestIR")
    if graph is not None and not isinstance(graph, EvidenceGraph):
        raise TypeError("graph must be an EvidenceGraph or None")
    ir.check_spans(utterance)
    ir_d0, g_d0 = ir_digest(ir), (graph.graph_digest if graph is not None else "")
    t_start = time.perf_counter()

    sel: Selection = select(ir, utterance, graph, budget)
    requests: list[ResolutionRequest] = []
    proposals: list[dict[str, Any]] = []
    findings: list[VerifierFinding] = []
    accepted: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    trace: list[TraceEntry] = []
    tel = {"calls_planned": sel.calls_planned if backend is not None else 0, "calls_made": 0, "retries": 0, "input_tokens": 0, "output_tokens": 0,
           "estimated_input_tokens": 0, "model_ms": 0.0, "verifier_ms": 0.0, "total_ms": 0.0, "backend_errors": 0,
           "zero_call_reason": sel.zero_call_rule if backend is not None else "no_backend",
           # G3H: planned = logical requests (selection); calls_made = actual backend attempts incl. retries, hard-capped by max_total_calls
           "attempts_by_path": {"node": 0, "coverage": 0}, "requests_not_sent": {"call_budget": 0, "input_budget": 0},
           "max_total_calls": budget.max_total_calls, "max_input_tokens": budget.max_input_tokens, "max_input_chars": budget.max_input_tokens * 4}
    warnings = [w.__dict__ if hasattr(w, "__dict__") else dict(w) for w in (graph.warnings if graph is not None else [])]
    warn_codes = sorted({w["code"] for w in warnings})
    allowed_ids = sorted({n.node_id for n in sel.nodes})

    if backend is not None and sel.outcome == "calls":
        idx = 0
        for n in sel.nodes:
            req = _node_request(ir, utterance, graph, n, sources_text, allowed_ids, warn_codes, budget, g_d0, ir_d0)
            prompt = prompts.build_node_prompt(req)
            req.prompt_digest = prompt_digest(prompt)
            requests.append(req)
            idx = _run_one(req, prompt, idx, backend, budget, seed, ir, utterance, graph, sources_text, None, proposals, findings, accepted,
                           coverage, unverified, trace, tel, n)
        if sel.coverage_calls_planned:
            gaps = [(g.char_start, g.char_end) for g in sel.gaps]
            req = ResolutionRequest(REQUEST_SCHEMA_VERSION, ir.digest, ir_d0, g_d0, "coverage", "coverage_gap",
                                    RequestSpan(0, len(utterance), utterance), RequestSpan(0, len(utterance), utterance), [], [], warn_codes,
                                    budget, prompts.PROMPT_VERSION)
            prompt = prompts.build_coverage_prompt(req, utterance, _node_summaries(ir), [(g.char_start, g.char_end, g.text) for g in sel.gaps])
            req.prompt_digest = prompt_digest(prompt)
            requests.append(req)
            idx = _run_one(req, prompt, idx, backend, budget, seed, ir, utterance, graph, sources_text, gaps, proposals, findings, accepted,
                           coverage, unverified, trace, tel, None)

    tel["total_ms"] = round((time.perf_counter() - t_start) * 1000.0, 3)
    tel["model_ms"] = round(tel["model_ms"], 3)
    tel["verifier_ms"] = round(tel["verifier_ms"], 3)
    if ir_digest(ir) != ir_d0 or (graph is not None and graph.graph_digest != g_d0):
        raise RuntimeError("G3 invariant violated: inputs changed during resolution")

    backend_desc = backend.describe() if backend is not None else {"kind": "none", "model_id": "none", "runtime": {}, "settings": {}}
    backend_desc = {"kind": backend_desc["kind"], "model_id": str(backend_desc["model_id"]), "runtime": dict(backend_desc.get("runtime") or {}),
                    "prompt_version": prompts.PROMPT_VERSION, "settings": dict(backend_desc.get("settings") or {})}
    ov = ResolutionOverlay(RESOLUTION_SCHEMA_VERSION, RESOLVER_VERSION, VERIFIER_VERSION, ir.digest, ir_d0, g_d0, backend_desc, sel.to_dict(),
                           [r.to_dict() for r in requests], proposals, [f.to_dict() for f in findings], accepted, coverage, unverified, warnings, tel,
                           list(NOTES))
    body = ov.to_dict()
    body.pop("overlay_digest")
    ov.overlay_digest = digest_of(body)
    return ResolveResult(ov, trace)


def _node_request(ir: S.RequestIR, utterance: str, graph: Optional[EvidenceGraph], n: SelectedNode, sources_text: Optional[dict[str, str]],
                  allowed_ids: list[str], warn_codes: list[str], budget: Budget, g_d: str, ir_d: str) -> ResolutionRequest:
    clause = RequestSpan(n.span.start, n.span.end, utterance[n.span.start:n.span.end])
    ctx = clause_context(utterance, n.span)
    cands = candidates_for(ir, graph, n, sources_text)
    req = ResolutionRequest(REQUEST_SCHEMA_VERSION, ir.digest, ir_d, g_d, "node", n.uncertainty_reason, clause, ctx, allowed_ids, cands,
                            warn_codes, budget, prompts.PROMPT_VERSION, n.node_id, n.node_kind)
    # trim candidates until the prompt fits the input budget (deterministic: drop from the tail). This is best effort only:
    # the exact assembled prompt is re-checked in _run_one before any call and is never sent when it still does not fit (F12).
    while len(req.candidates) > 1 and prompts.estimate_tokens(prompts.build_node_prompt(req)) > budget.max_input_tokens:
        req.candidates = req.candidates[:-1]
    errs = validate_request(req.to_dict())
    if errs:
        raise RuntimeError("G3 built an invalid ResolutionRequest: " + errs[0])
    return req


def _run_one(req: ResolutionRequest, prompt: str, idx: int, backend: ResolverBackend, budget: Budget, seed: int, ir: S.RequestIR, utterance: str,
             graph: Optional[EvidenceGraph], sources_text: Optional[dict[str, str]], gaps: Optional[list[tuple[int, int]]],
             proposals: list, findings: list, accepted: list, coverage: list, unverified: list, trace: list, tel: dict,
             n: Optional[SelectedNode]) -> int:
    est = prompts.estimate_tokens(prompt)
    tel["estimated_input_tokens"] += est
    vms = 0.0
    remaining = budget.max_total_calls - tel["calls_made"]
    if remaining <= 0:
        # F11: the hard cap counts actual attempts; nothing is sent once it is reached
        err, attempts, bres = f"total call budget exhausted ({tel['calls_made']}/{budget.max_total_calls} attempts used)", 0, None
        tel["requests_not_sent"]["call_budget"] += 1
        res = verify(req, None, ir, utterance, graph, sources_text, proposal_index=idx, backend_error=err, gaps=gaps, not_sent="call_budget")
    elif est > budget.max_input_tokens or len(prompt) > budget.max_input_tokens * 4:
        # F12: the exact assembled prompt is checked before every call; an oversized prompt is never sent, nothing is truncated invisibly
        err, attempts, bres = f"input budget exceeded (estimated {est} tokens / {len(prompt)} chars > {budget.max_input_tokens} tokens)", 0, None
        tel["requests_not_sent"]["input_budget"] += 1
        res = verify(req, None, ir, utterance, graph, sources_text, proposal_index=idx, backend_error=err, gaps=gaps, not_sent="input_budget")
    else:
        bres, err, attempts = _call(backend, prompt, budget, seed, remaining)
        tel["calls_made"] += attempts
        tel["attempts_by_path"][req.path] += attempts
        tel["retries"] += max(0, attempts - 1)
        if bres is not None:
            tel["input_tokens"] += bres.input_tokens
            tel["output_tokens"] += bres.output_tokens
            tel["model_ms"] += bres.elapsed_ms
        else:
            tel["backend_errors"] += 1
        t0 = time.perf_counter()
        res = verify(req, bres.text if bres is not None else None, ir, utterance, graph, sources_text, proposal_index=idx, backend_error=err, gaps=gaps)
        vms = (time.perf_counter() - t0) * 1000.0
        tel["verifier_ms"] += vms
    proposals.append(res.proposal if res.proposal is not None else {"raw_rejected": True, "reason": err or "rejected before parsing"})
    findings.extend(res.findings)
    accepted.extend(res.accepted)
    unverified.extend(res.unverified)
    coverage.extend(res.coverage)
    disp = sorted({f.disposition for f in res.findings})
    trace.append(TraceEntry(idx, req.path, req.node_id, req.uncertainty_reason, n.rule_id if n else "g3.sel.coverage.gap",
                            [c.ref for c in req.candidates], req.prompt_digest, est, backend.kind, str(backend.model_id),
                            bres.input_tokens if bres else 0, bres.output_tokens if bres else 0, bres.elapsed_ms if bres else 0.0,
                            round(vms, 3), attempts, "/".join(disp) or "REJECT", sorted({r for f in res.findings for r in f.rule_ids})))
    return idx + 1
