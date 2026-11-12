"""DCE-G3 — deterministic candidate selection, coverage accounting and bounded evidence slices.

Decision table (rule ids ``g3.sel.*``) — evaluated in order, first zero-call rule wins:

| id | condition | outcome |
|---|---|---|
| g3.sel.zero.rejected_request        | ``ir.status`` in (rejected_too_large, rejected_invalid_text, empty) | 0 calls |
| g3.sel.zero.language_not_english    | ``ir.language_scope != "en"`` or ``ir.language_hint not in ("en",)`` | 0 calls |
| g3.sel.zero.unsupported_unresolved  | any unresolved node of kind unsupported_language / unsupported_script / truncated | 0 calls |
| g3.sel.zero.graph_digest_mismatch   | the EvidenceGraph was built for another utterance | 0 calls |
| g3.sel.node.unresolved              | unresolved node of kind ambiguous_referent / vague_object / no_recognized_action | 1 node call each (capped) |
| g3.sel.node.unresolved_reference    | objective with a reference whose status is ``unresolved`` | 1 node call each (capped) |
| g3.sel.coverage.gap                 | deterministic coverage accounting finds >= 1 residual instruction-like segment | 1 coverage call (capped) |
| g3.sel.zero.fully_covered           | no node selected and no gap | 0 calls |

Coverage accounting is span arithmetic only: utterance sentence segments minus the union of the RequestIR spans G1
classified as actionable or structural (objectives, constraints, conditions, unresolved, protected regions). Context
statements (``k*``) are *not* subtracted — a missed objective usually lands there — so they surface as residuals. A residual
segment counts as a *gap* when it has at least ``MIN_GAP_WORDS`` words and one alphabetic token that is not a stop word.
No grammar, no action lexicon: this is the *detection* half; the *audit* half is the (optional, budgeted) model call.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from forge_squid.request_ir import schema as S
from forge_squid.request_ir.evidence_graph import EvidenceGraph

from .contracts import Budget, Candidate, Locator, RequestSpan

NODE_UNRESOLVED_KINDS = ("ambiguous_referent", "vague_object", "no_recognized_action")
ZERO_UNRESOLVED_KINDS = ("unsupported_language", "unsupported_script", "truncated")
MIN_GAP_WORDS = 3
_SENT_RE = re.compile(r"(?:[^.!?;\n]|\.(?=\S))+(?:[.!?;]+(?=\s|$)|\n)*")   # a dot followed by non-space (prod.yaml) does not end a sentence
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_STOP = {"the", "a", "an", "and", "or", "but", "then", "also", "please", "thanks", "thank", "you", "it", "this", "that", "these", "those",
         "of", "to", "in", "on", "for", "with", "as", "by", "at", "from", "is", "are", "be", "so", "if", "not", "no", "yes", "ok", "okay"}


@dataclass
class SelectedNode:
    node_id: str
    node_kind: str                    # unresolved kind or "unresolved_reference"
    uncertainty_reason: str
    rule_id: str
    span: S.Span
    text: str


@dataclass
class CoverageGap:
    char_start: int
    char_end: int
    text: str


@dataclass
class Selection:
    outcome: str                      # "zero_calls" | "calls"
    zero_call_rule: Optional[str]
    nodes: list[SelectedNode] = field(default_factory=list)
    gaps: list[CoverageGap] = field(default_factory=list)
    calls_planned: int = 0
    node_calls_planned: int = 0
    coverage_calls_planned: int = 0
    dropped_for_budget: list[str] = field(default_factory=list)
    rules_fired: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "zero_call_rule": self.zero_call_rule, "rules_fired": self.rules_fired,
                "nodes": [{"node_id": n.node_id, "node_kind": n.node_kind, "uncertainty_reason": n.uncertainty_reason, "rule_id": n.rule_id,
                           "char_start": n.span.start, "char_end": n.span.end} for n in self.nodes],
                "gaps": [{"char_start": g.char_start, "char_end": g.char_end, "text": g.text} for g in self.gaps],
                "calls_planned": self.calls_planned, "node_calls_planned": self.node_calls_planned,
                "coverage_calls_planned": self.coverage_calls_planned, "dropped_for_budget": self.dropped_for_budget}


def _covered_spans(ir: S.RequestIR) -> list[tuple[int, int]]:
    """Spans G1 classified as actionable or structural. Context statements (``k*``) are deliberately *not* covered: when G1
    misses an objective it usually lands there, so they are what the coverage audit looks at."""
    g = ir.graph
    out = [(o.source_span.start, o.source_span.end) for o in g.objectives]
    out += [(c.source_span.start, c.source_span.end) for c in g.constraints]
    out += [(q.source_span.start, q.source_span.end) for q in g.conditions]
    out += [(u.source_span.start, u.source_span.end) for u in g.unresolved]
    out += [(p.source_span.start, p.source_span.end) for p in g.protected_regions]
    return sorted(out)


def coverage_gaps(ir: S.RequestIR, utterance: str) -> list[CoverageGap]:
    covered = _covered_spans(ir)
    gaps: list[CoverageGap] = []
    for m in _SENT_RE.finditer(utterance):
        a, b = m.start(), m.end()
        cursor = a
        pieces: list[tuple[int, int]] = []
        for s, e in covered:
            if e <= cursor or s >= b:
                continue
            if s > cursor:
                pieces.append((cursor, min(s, b)))
            cursor = max(cursor, e)
        if cursor < b:
            pieces.append((cursor, b))
        for s, e in pieces:
            seg = utterance[s:e]
            words = _WORD_RE.findall(seg)
            if len(words) >= MIN_GAP_WORDS and any(w.lower() not in _STOP for w in words):
                lead = len(seg) - len(seg.lstrip())
                trail = len(seg) - len(seg.rstrip(" \t\n.;!?,"))
                s2, e2 = s + lead, e - trail
                if e2 > s2:
                    gaps.append(CoverageGap(s2, e2, utterance[s2:e2]))
    return gaps


def select(ir: S.RequestIR, utterance: str, graph: Optional[EvidenceGraph], budget: Budget) -> Selection:
    fired: list[str] = []
    if ir.status in ("rejected_too_large", "rejected_invalid_text", "empty"):
        return Selection("zero_calls", "g3.sel.zero.rejected_request", rules_fired=["g3.sel.zero.rejected_request"])
    if ir.language_scope != "en" or ir.language_hint != "en":
        return Selection("zero_calls", "g3.sel.zero.language_not_english", rules_fired=["g3.sel.zero.language_not_english"])
    if any(u.kind in ZERO_UNRESOLVED_KINDS for u in ir.graph.unresolved):
        return Selection("zero_calls", "g3.sel.zero.unsupported_unresolved", rules_fired=["g3.sel.zero.unsupported_unresolved"])
    if graph is not None and graph.request_digest != ir.digest:
        return Selection("zero_calls", "g3.sel.zero.graph_digest_mismatch", rules_fired=["g3.sel.zero.graph_digest_mismatch"])

    nodes: list[SelectedNode] = []
    for u in ir.graph.unresolved:
        if u.kind in NODE_UNRESOLVED_KINDS:
            nodes.append(SelectedNode(u.id, u.kind, u.kind, "g3.sel.node.unresolved", u.source_span, u.text))
            fired.append("g3.sel.node.unresolved")
    for o in ir.graph.objectives:
        if any(r.status == "unresolved" for r in o.references):
            nodes.append(SelectedNode(o.id, "unresolved_reference", "unresolved_reference", "g3.sel.node.unresolved_reference", o.source_span, o.text))
            fired.append("g3.sel.node.unresolved_reference")
    nodes.sort(key=lambda n: (n.span.start, n.node_id))
    gaps = coverage_gaps(ir, utterance)
    if gaps:
        fired.append("g3.sel.coverage.gap")
    if not nodes and not gaps:
        return Selection("zero_calls", "g3.sel.zero.fully_covered", rules_fired=["g3.sel.zero.fully_covered"])

    dropped = [n.node_id for n in nodes[budget.max_node_calls:]]
    nodes = nodes[:budget.max_node_calls]
    node_calls = len(nodes)
    cov_calls = min(1 if gaps else 0, budget.max_coverage_calls)
    if node_calls + cov_calls > budget.max_total_calls:
        over = node_calls + cov_calls - budget.max_total_calls
        if cov_calls and over:
            cov_calls, over = 0, over - 1
            dropped.append("coverage")
        if over:
            dropped += [n.node_id for n in nodes[len(nodes) - over:]]
            nodes = nodes[:len(nodes) - over]
            node_calls = len(nodes)
    return Selection("calls", None, nodes, gaps, node_calls + cov_calls, node_calls, cov_calls, dropped, sorted(set(fired)))


# ---------------------------------------------------------------------------------------------------- bounded slices ---
def clause_context(utterance: str, span: S.Span, *, radius: int = 1) -> RequestSpan:
    """The sentence containing ``span`` plus ``radius`` sentences either side (bounded context, exact offsets)."""
    sents = [(m.start(), m.end()) for m in _SENT_RE.finditer(utterance)] or [(0, len(utterance))]
    idx = next((i for i, (a, b) in enumerate(sents) if a <= span.start < b), 0)
    a = sents[max(0, idx - radius)][0]
    b = sents[min(len(sents) - 1, idx + radius)][1]
    return RequestSpan(a, b, utterance[a:b])


def candidates_for(ir: S.RequestIR, graph: Optional[EvidenceGraph], node: SelectedNode, sources_text: Optional[dict[str, str]],
                   *, max_candidates: int = 12, excerpt_chars: int = 160) -> list[Candidate]:
    """Request-node antecedents (preceding objectives / context statements) first, then G2 evidence for the node
    (candidate-antecedent edges included), then whole-source links. Bounded, deterministic order."""
    out: list[Candidate] = []
    seen: dict[str, int] = {}
    # G3H D3: one evidence node can carry several G2 edges (a value token is both a lexical `mentions` and the `supports` /
    # `contradicts` side). The candidate keeps the strongest kind so the verifier's via_kind gate can admit a typed reading.
    strength = {"supports": 3, "contradicts": 3, "constrains": 2, "candidate_antecedent": 2, "mentions": 1}

    def add(c: Candidate) -> None:
        if c.ref in seen:
            i = seen[c.ref]
            if strength.get(c.via_kind or "", 0) > strength.get(out[i].via_kind or "", 0):
                out[i] = c
        elif len(out) < max_candidates:
            seen[c.ref] = len(out)
            out.append(c)

    preceding = sorted([*ir.graph.objectives, *ir.graph.context_statements], key=lambda n: n.source_span.start)
    for n in reversed([p for p in preceding if p.source_span.start < node.span.start and p.id != node.node_id]):
        add(Candidate(f"node:{n.id}", n.text[:excerpt_chars]))
        if len([c for c in out if c.ref.startswith("node:")]) >= 3:
            break
    if graph is not None:
        paths = {s.source_id: s.normalized_safe_path for s in graph.sources}
        for e in graph.edges_from(node.node_id):
            en = graph.node(e.to_evidence_node_id)
            sp = en.span
            add(Candidate(f"evidence:{en.id}", sp.text[:excerpt_chars], Locator(sp.source_id, paths.get(sp.source_id, ""), sp.char_start, sp.char_end),
                          e.kind, e.rule_id))
        for se in graph.source_edges_from(node.node_id):
            add(Candidate(f"source:{se.to_source_id}", paths.get(se.to_source_id, ""), None, se.kind, se.rule_id))
    return out
