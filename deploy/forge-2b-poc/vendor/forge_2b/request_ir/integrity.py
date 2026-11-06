"""DCE-G1R3E — graph-integrity check (conventions v6 rule 34: no silent objective loss).

Read-only, deterministic, additive. Given a ``RequestIR`` (and the utterance it was parsed from) it reports every place where
directive text may have been dropped without a trace, or where graph references are broken. It never changes the IR, never
authorizes anything and never executes anything. Consumers that gate on safety should treat **any** finding of severity
``"error"`` as REQUIRE_RESOLUTION — a request whose graph is incomplete cannot be classified as safe.

Findings
--------
``empty_graph``           — the utterance has unprotected, non-punctuation text but the graph carries no objective, constraint,
                            condition, unresolved node or context statement at all.
``uncovered_sentence``    — a sentence (outside protected regions) with at least one alphabetic word that no node span touches.
``dangling_condition``    — a condition with no ``applies_to_ids`` (severity ``"info"``: legitimate for a hypothetical opener that
                            is closed by a full stop or a question mark — v6 rule 27 — but worth surfacing).
``broken_reference``      — a link, condition or objective-scoped constraint that names a node id which does not exist.
``objective_without_span`` — an objective whose span is empty or outside the utterance.

``integrity_ok(ir, utterance)`` is ``True`` when no finding has severity ``"error"``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .schema import RequestIR

INTEGRITY_VERSION = "dce-g1r3e/0.1.0"

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")
_WORD_RE = re.compile(r"[^\W\d_]{2,}", re.UNICODE)


@dataclass
class IntegrityFinding:
    kind: str                       # empty_graph | uncovered_sentence | dangling_condition | broken_reference | objective_without_span
    severity: str                   # "error" | "info"
    text: str
    start: Optional[int] = None
    end: Optional[int] = None
    node_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "severity": self.severity, "text": self.text, "start": self.start, "end": self.end, "node_id": self.node_id}


@dataclass
class IntegrityReport:
    version: str
    ok: bool
    findings: list[IntegrityFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"version": self.version, "ok": self.ok, "findings": [f.to_dict() for f in self.findings]}


def _node_spans(ir: RequestIR) -> list[tuple[int, int]]:
    g = ir.graph
    spans: list[tuple[int, int]] = []
    for coll in (g.objectives, g.constraints, g.conditions, g.unresolved, g.context_statements, g.protected_regions, g.links):
        for n in coll:
            sp = getattr(n, "source_span", None)
            if sp is not None and sp.end > sp.start:
                spans.append((sp.start, sp.end))
    for o in g.objectives:                       # an objective's trigger / target may extend beyond its own span
        for part in (getattr(o, "trigger", None), getattr(o, "target", None)):
            sp = getattr(part, "source_span", None)
            if sp is not None and sp.end > sp.start:
                spans.append((sp.start, sp.end))
    return spans


def _overlaps(spans: list[tuple[int, int]], a: int, b: int) -> bool:
    return any(s < b and a < e for s, e in spans)


def integrity_findings(ir: RequestIR, utterance: str) -> list[IntegrityFinding]:
    """All integrity findings for ``ir`` parsed from ``utterance`` (deterministic order: by start offset, then kind)."""
    g = ir.graph
    out: list[IntegrityFinding] = []
    ids = {n.id for coll in (g.objectives, g.constraints, g.conditions, g.unresolved, g.context_statements, g.protected_regions, g.links) for n in coll}
    protected = [(p.source_span.start, p.source_span.end) for p in g.protected_regions]
    spans = _node_spans(ir)

    # 1. empty graph over real text
    unprotected = "".join(ch if not _overlaps(protected, i, i + 1) else " " for i, ch in enumerate(utterance))
    has_words = bool(_WORD_RE.search(unprotected))
    if has_words and not (g.objectives or g.constraints or g.conditions or g.unresolved or g.context_statements):
        a, b = len(utterance) - len(utterance.lstrip()), len(utterance.rstrip())
        out.append(IntegrityFinding("empty_graph", "error", utterance[a:b], a, b))

    # 2. uncovered sentences
    pos = 0
    for piece in _SENT_SPLIT_RE.split(utterance):
        if not piece:
            continue
        a = utterance.index(piece, pos)
        b = a + len(piece)
        pos = b
        if _overlaps(protected, a, b) and not _WORD_RE.search(unprotected[a:b]):
            continue
        if not _WORD_RE.search(unprotected[a:b]):
            continue
        if not _overlaps(spans, a, b):
            out.append(IntegrityFinding("uncovered_sentence", "error", piece.strip(), a, b))

    # 3. dangling conditions
    for q in g.conditions:
        if not q.applies_to_ids:
            out.append(IntegrityFinding("dangling_condition", "info", q.text, q.source_span.start, q.source_span.end, q.id))

    # 4. broken references
    for q in g.conditions:
        for t in q.applies_to_ids:
            if t not in ids:
                out.append(IntegrityFinding("broken_reference", "error", f"{q.id} -> {t}", q.source_span.start, q.source_span.end, q.id))
        if q.negates is not None and q.negates not in ids:
            out.append(IntegrityFinding("broken_reference", "error", f"{q.id} negates {q.negates}", q.source_span.start, q.source_span.end, q.id))
    for c in g.constraints:
        for t in c.applies_to_objective_ids:
            if t not in ids:
                out.append(IntegrityFinding("broken_reference", "error", f"{c.id} -> {t}", c.source_span.start, c.source_span.end, c.id))
    for l in g.links:
        for t in (l.from_id, l.to_id):
            if t not in ids:
                out.append(IntegrityFinding("broken_reference", "error", f"{l.id} -> {t}", l.source_span.start, l.source_span.end, l.id))
    for u in g.unresolved:
        if u.objective_id is not None and u.objective_id not in ids:
            out.append(IntegrityFinding("broken_reference", "error", f"{u.id} -> {u.objective_id}", u.source_span.start, u.source_span.end, u.id))

    # 5. objectives without a usable span
    n = len(utterance)
    for o in g.objectives:
        sp = o.source_span
        if sp.end <= sp.start or sp.start < 0 or sp.end > n:
            out.append(IntegrityFinding("objective_without_span", "error", o.text, sp.start, sp.end, o.id))

    out.sort(key=lambda f: ((f.start if f.start is not None else -1), f.kind, f.node_id or ""))
    return out


def integrity_report(ir: RequestIR, utterance: str) -> IntegrityReport:
    findings = integrity_findings(ir, utterance)
    return IntegrityReport(INTEGRITY_VERSION, not any(f.severity == "error" for f in findings), findings)


def integrity_ok(ir: RequestIR, utterance: str) -> bool:
    return integrity_report(ir, utterance).ok


__all__ = ["INTEGRITY_VERSION", "IntegrityFinding", "IntegrityReport", "integrity_findings", "integrity_report", "integrity_ok"]
