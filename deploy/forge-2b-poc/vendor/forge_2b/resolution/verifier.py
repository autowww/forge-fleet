"""DCE-G3 — deterministic verifier. Rule ids ``g3.v.*``. Fails closed: anything not positively verified is REJECT.

What is checked independently of the model and of G2's own validator:

1. ids rebind to the *original* RequestIR (digest + node existence); every proposed request span is an exact slice.
2. evidence refs rebind to the EvidenceGraph (digest), the span text round-trips against the source text and its digest.
3. typed ``supports`` / ``contradicts`` are **recomputed** from the two literal spans with the conventions' rule 2 (an edge whose
   stored kind disagrees with the recomputation is "forged" — see G2 review F2).
4. explicit file scope (G2 review F1, hardened in G3H after review F8/F9): file names in the clause are resolved against the
   graph's *sources* by exact normalised path, or by basename only when exactly one source carries it; an ambiguous basename
   ⇒ ``g3.v.scope_ambiguous_source``. A typed reading from a source outside the clause's scope is rejected unless a sentence
   in the bounded context *asks for a comparison and names both the scoped source and the evidence source* (or the clause
   itself asks for the comparison and names the evidence source). A bare "compare"/"all files" cue never unlocks scope.
5. monotonic policy: no authorization vocabulary, no readings on constraint / protected nodes, no attachment text promoted.
6. fabricated or missing refs, contradictory readings, non-English output ⇒ REJECT; ``abstain`` ⇒ ABSTAIN.
7. invalid JSON, oversized output, schema violations, forbidden keys, backend nonresponse ⇒ REJECT; a request the resolver
   did not send because a budget would be exceeded ⇒ REJECT with ``g3.v.call_budget_exhausted`` / ``g3.v.input_budget_exceeded``.
8. trust boundary (review F10): only ``antecedent`` (ref rebinds) and ``supports``/``contradicts`` (edge recomputed) readings
   are ACCEPT_ADVISORY; ``interpretation`` readings are ACCEPT_UNVERIFIED — recorded apart, never evidence-backed. Any reading
   whose text carries a numeric literal found neither in the clause/context nor in a candidate excerpt ⇒ ``g3.v.unanchored_literal``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from forge_2b.request_ir import schema as S
from forge_2b.request_ir.evidence_graph import EvidenceGraph

from .contracts import (COVERAGE_STATUS, PROPOSAL_SCHEMA_VERSION, UNVERIFIED_STATUS, VERIFIED_RELATIONS, EvidenceRef, RequestSpan,
                        ResolutionRequest, VerifierFinding, text_digest, validate_model_output)

_POLICY_RE = re.compile(
    r"\b(allow(?:ed|s|ing)?|authori[sz]\w*|approv\w*|permit\w*|permission|override|bypass|ignore the|safe to|go ahead|"
    r"no longer (?:required|needed|forbidden|prohibited)|lift(?:ed|s)? the|remove the (?:restriction|prohibition|constraint)|"
    r"execute|schedule|run (?:it|them|the command)|proceed with)\b", re.I)
_FILE_RE = re.compile(r"(?<![\w/.-])([\w.\-]+(?:/[\w.\-]+)*\.(?:ya?ml|json|csv|md|txt|env|log|ini|toml|cfg|conf|zip|py|js|ts|sh))(?![\w/.-])", re.I)
_CROSS_FILE_RE = re.compile(r"\b(compar\w*|everywhere|all (?:the )?files|each file|every file|both files|across (?:the )?files|in all|consistent)\b", re.I)
_SENT_RE = re.compile(r"(?:[^.!?;\n]|\.(?=\S))+(?:[.!?;]+(?=\s|$)|\n)*")   # same splitter as selection.clause_context
_UNIT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)\s?(ms|s|m|h|d|%)$")
_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
# numeric literals inside free text (review F10 anchoring): whole tokens, decimals allowed, dotted/identifier tokens excluded;
# a sentence-ending period after the number does not hide it (G3H D2).
_LITERAL_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w|\.\d)")
_SEGMENT_SPLIT_RE = re.compile(r"[\"'“”‘’`|]|:\s")   # quote marks, table bars, "key: " separators (promotion granularity, G3H D4)
_QUOTED_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|“[^”\n]*”|‘[^’\n]*’|`[^`\n]*`")
_MIN_PROMOTION_LINE = 20

BUDGET_RULES = {"call_budget": "g3.v.call_budget_exhausted", "input_budget": "g3.v.input_budget_exceeded"}


# ------------------------------------------------------------------------------------------- typed recomputation ---
def normalize_scalar(v: str) -> tuple[str, Any]:
    """Conventions rule 2, re-implemented here (independent of evidence_graph._normalize_scalar)."""
    t = v.strip().strip("`\"'").strip().lower()
    if _NUM_RE.fullmatch(t):
        return "number", float(t)
    m = _UNIT_RE.fullmatch(t)
    if m:
        return f"number:{m.group(2)}", float(m.group(1))
    if t in ("true", "yes", "on", "enabled"):
        return "bool", True
    if t in ("false", "no", "off", "disabled"):
        return "bool", False
    return "string", t


@dataclass(frozen=True)
class TypedAudit:
    edge_id: str
    ok: bool
    expected_kind: Optional[str]
    stored_kind: str
    reasons: tuple[str, ...]


def audit_typed_edges(graph: EvidenceGraph, ir: S.RequestIR, sources_text: Optional[dict[str, str]]) -> list[TypedAudit]:
    """Recompute every supports/contradicts edge from its literal spans. ``sources_text`` maps source_id -> decoded text."""
    node_text = {n.id: n.text for n in (*ir.graph.objectives, *ir.graph.constraints, *ir.graph.conditions, *ir.graph.unresolved,
                                        *ir.graph.context_statements)}
    out: list[TypedAudit] = []
    for e in graph.edges:
        if e.kind not in ("supports", "contradicts"):
            continue
        reasons: list[str] = []
        j = e.justification or {}
        rs, es = j.get("request_side") or {}, j.get("evidence_side") or {}
        rtext = node_text.get(rs.get("node_id", ""))
        if rtext is None or rs.get("node_id") != e.from_request_node_id:
            reasons.append("request_side.node_id does not rebind to the RequestIR")
        else:
            local = rtext[int(rs.get("local_start", 0)):int(rs.get("local_end", 0))]
            if str(rs.get("value", "")) not in local or str(rs.get("key", "")) not in local:
                reasons.append("request_side key/value not inside the cited request slice")
        if sources_text is not None:
            st = sources_text.get(es.get("source_id", ""))
            vs = es.get("value_span") or [0, 0]
            if st is None:
                reasons.append("evidence_side.source_id not among the given sources")
            elif st[int(vs[0]):int(vs[1])] != str(es.get("value", "")):
                reasons.append("evidence_side value does not round-trip to the source slice")
        try:
            en = graph.node(e.to_evidence_node_id)
            if en.span.source_id != es.get("source_id"):
                reasons.append("evidence node source differs from evidence_side.source_id")
        except KeyError:
            reasons.append("to_evidence_node_id not in graph")
        rt, rv = normalize_scalar(str(rs.get("value", "")))
        et, ev = normalize_scalar(str(es.get("value", "")))
        expected: Optional[str]
        if rt != et:
            expected = None
            reasons.append(f"values not comparable ({rt} vs {et}); a typed edge is not permitted")
        else:
            equal = abs(rv - ev) < 1e-9 if isinstance(rv, float) else rv == ev
            expected = "supports" if equal else "contradicts"
            if expected != e.kind:
                reasons.append(f"recomputed {expected} but edge says {e.kind}")
            if j.get("comparison") not in ("equal" if equal else "different",):
                reasons.append("justification.comparison disagrees with recomputation")
        out.append(TypedAudit(e.id, not reasons, expected, e.kind, tuple(reasons)))
    return out


# ------------------------------------------------------------------------------------------------------ helpers ---
def _is_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    latin = sum(1 for c in letters if ord(c) < 0x250)
    return latin / len(letters) >= 0.9


def _attachment_lines(sources_text: Optional[dict[str, str]]) -> list[str]:
    if not sources_text:
        return []
    out = []
    for t in sources_text.values():
        for ln in t.splitlines():
            s = ln.strip()
            if len(s) >= _MIN_PROMOTION_LINE:
                out.append(s.lower())
            # G3H D4: a quoted string value (JSON/YAML), a table cell, or a key: value tail copied verbatim is promotion too
            for seg in _SEGMENT_SPLIT_RE.split(s):
                seg = seg.strip()
                if len(seg) >= _MIN_PROMOTION_LINE and seg != s:
                    out.append(seg.lower())
    return out


def _promoted(text: str, lines: list[str]) -> bool:
    low = text.lower()
    return any(ln in low for ln in lines)


def _file_mentions(ir: S.RequestIR, utterance: str, start: int, end: int, *, masked: Optional[str] = None) -> set[str]:
    """File names written in ``utterance[start:end]`` (regex + G1 path/attachment protected regions), lower-cased, as written.
    ``masked`` (same length as the slice, quoted spans blanked) restricts the search to unquoted text."""
    names: set[str] = set()
    text = masked if masked is not None else utterance[start:end]
    for m in _FILE_RE.finditer(text):
        names.add(m.group(1).lower().lstrip("./"))
    for p in ir.graph.protected_regions:
        if p.kind in ("path", "attachment") and start <= p.source_span.start and p.source_span.end <= end:
            if masked is not None and masked[p.source_span.start - start:p.source_span.end - start].strip() == "":
                continue
            names.add(utterance[p.source_span.start:p.source_span.end].strip("`'\" ").lower().lstrip("./"))
    return names


def _sources_for_mention(mention: str, span_paths: dict[str, str]) -> set[str]:
    """Source ids a written file name may denote (review F9). A mention with a directory component is matched as a normalised
    path (exact, then ZIP-member / path suffix). A bare basename matches *every* source whose basename equals it — a root-level
    ``prod.yaml`` does not win over ``configs/prod.yaml``; the caller treats >1 hit as ambiguous and fails closed."""
    m = mention.lower()
    if "/" in m:
        exact = {sid for sid, p in span_paths.items() if p.lower() == m or p.lower().split("!", 1)[-1] == m}
        if exact:
            return exact
        return {sid for sid, p in span_paths.items() if p.lower().endswith("/" + m) or p.lower().endswith("!" + m)}
    return {sid for sid, p in span_paths.items() if p.lower().rsplit("/", 1)[-1].rsplit("!", 1)[-1] == m}


@dataclass(frozen=True)
class Scope:
    mentioned: tuple[str, ...]            # file names written in the clause
    source_ids: frozenset[str]            # sources the clause unambiguously denotes
    ambiguous: tuple[str, ...]            # mentions that denote more than one source
    unmatched: tuple[str, ...]            # mentions that denote no attached source


def clause_scope(ir: S.RequestIR, utterance: str, span: S.Span, span_paths: dict[str, str]) -> Scope:
    mentions = sorted(_file_mentions(ir, utterance, span.start, span.end))
    ids: set[str] = set()
    amb: list[str] = []
    unm: list[str] = []
    for m in mentions:
        hits = _sources_for_mention(m, span_paths)
        if len(hits) == 1:
            ids |= hits
        elif len(hits) > 1:
            amb.append(m)
        else:
            unm.append(m)
    return Scope(tuple(mentions), frozenset(ids), tuple(amb), tuple(unm))


def comparison_binds(ir: S.RequestIR, utterance: str, context: RequestSpan, clause: S.Span, scope_ids: frozenset[str],
                     evidence_sid: str, span_paths: dict[str, str]) -> bool:
    """Review F8: a cross-file typed reading is admissible only when some sentence of the bounded context asks for a comparison
    *and* names the evidence source unambiguously, and that sentence either is the clause itself or also names a scoped source.
    A comparison of unrelated files, or a bare cue, binds nothing."""
    for m in _SENT_RE.finditer(utterance[context.char_start:context.char_end]):
        s_start, s_end = context.char_start + m.start(), context.char_start + m.end()
        # G3H D1: quoted text is reported speech, not a request — a cue or a file name inside quotes binds nothing
        unquoted = _QUOTED_RE.sub(lambda q: " " * len(q.group(0)), m.group(0))
        if not _CROSS_FILE_RE.search(unquoted):
            continue
        named: dict[str, set[str]] = {n: _sources_for_mention(n, span_paths)
                                      for n in _file_mentions(ir, utterance, s_start, s_end, masked=unquoted)}
        names_evidence = any(h == {evidence_sid} for h in named.values())
        if not names_evidence:
            continue
        is_clause = s_start <= clause.start and clause.end <= s_end
        names_scoped = any(h and h <= scope_ids for h in named.values())
        if is_clause or names_scoped:
            return True
    return False


def unanchored_literals(text: str, anchors: list[str]) -> list[str]:
    """Numeric literals in ``text`` that occur in none of ``anchors`` (clause, context, candidate excerpts). Review F10."""
    pool = " ".join(anchors).lower()
    present = set(_LITERAL_RE.findall(pool))
    return sorted({lit for lit in _LITERAL_RE.findall(text) if lit not in present})


def _node_span(ir: S.RequestIR, node_id: str) -> Optional[S.Span]:
    for coll in (ir.graph.objectives, ir.graph.constraints, ir.graph.conditions, ir.graph.unresolved, ir.graph.context_statements,
                 ir.graph.protected_regions):
        for n in coll:
            if n.id == node_id:
                return n.source_span
    return None


def _ir_node_ids(ir: S.RequestIR) -> set[str]:
    g = ir.graph
    return {n.id for coll in (g.objectives, g.constraints, g.conditions, g.unresolved, g.context_statements, g.protected_regions) for n in coll}


def canonicalise_antecedent_ref(ref: str, offered: dict[str, Any]) -> str:
    """G3V-014: map model shorthand to the sole offered ref when unique (no new refs invented)."""
    if not ref or ref in offered:
        return ref
    by_tail: dict[str, list[str]] = {}
    for r in offered:
        tail = r.split(":", 1)[-1]
        by_tail.setdefault(tail, []).append(r)
    tail = ref.split(":", 1)[-1]
    if tail in by_tail and len(by_tail[tail]) == 1:
        return by_tail[tail][0]
    hits = [r for r in offered if r.endswith(ref) or ref == r.split(":", 1)[-1]]
    if len(hits) == 1:
        return hits[0]
    return ref


# --------------------------------------------------------------------------------------------------------- verify ---
@dataclass
class VerifyResult:
    proposal: Optional[dict[str, Any]]
    findings: list[VerifierFinding]
    accepted: list[dict[str, Any]]
    coverage: list[dict[str, Any]]
    unverified: list[dict[str, Any]] = field(default_factory=list)


def verify(req: ResolutionRequest, model_text: Optional[str], ir: S.RequestIR, utterance: str, graph: Optional[EvidenceGraph],
           sources_text: Optional[dict[str, str]], *, proposal_index: int, backend_error: Optional[str] = None,
           gaps: Optional[list[tuple[int, int]]] = None, not_sent: Optional[str] = None) -> VerifyResult:
    """``not_sent`` names a budget (key of ``BUDGET_RULES``) when the resolver did not call the backend at all."""
    F: list[VerifierFinding] = []

    def rej(rules: list[str], detail: str, item: Optional[int] = None, node: Optional[str] = None, rs: Optional[RequestSpan] = None,
            ev: Optional[list[EvidenceRef]] = None) -> None:
        F.append(VerifierFinding(proposal_index, req.path, "REJECT", rules, detail, node or req.node_id, item, rs, ev or []))

    if not_sent is not None:
        rej([BUDGET_RULES[not_sent]], backend_error or f"request not sent: {not_sent}")
        return VerifyResult(None, F, [], [])
    if backend_error is not None or model_text is None:
        rej(["g3.v.backend_nonresponse"], backend_error or "no model output")
        return VerifyResult(None, F, [], [])
    if len(model_text) > req.budget.max_output_chars:
        rej(["g3.v.oversized_output"], f"{len(model_text)} chars > {req.budget.max_output_chars}")
        return VerifyResult(None, F, [], [])
    try:
        doc = json.loads(model_text)
    except ValueError:
        rej(["g3.v.invalid_json"], "model output is not valid JSON")
        return VerifyResult(None, F, [], [])
    errs = validate_model_output(doc)
    if errs:
        rules = ["g3.v.forbidden_key" if any("forbidden key" in e for e in errs) else "g3.v.schema_violation"]
        rej(rules, "; ".join(errs[:3]))
        return VerifyResult(None, F, [], [])

    proposal = {"schema_version": PROPOSAL_SCHEMA_VERSION, "abstain": bool(doc["abstain"]), "reason": doc["reason"],
                "readings": [dict(r, antecedent_ref=r.get("antecedent_ref")) for r in doc.get("readings", [])],
                "coverage_candidates": [dict(c, status=COVERAGE_STATUS, suggested_action=c.get("suggested_action")) for c in doc.get("coverage_candidates", [])]}

    if ir.digest != req.request_digest:
        rej(["g3.v.request_digest_mismatch"], "request digest differs from the RequestIR")
        return VerifyResult(proposal, F, [], [])
    if graph is not None and graph.graph_digest != req.graph_digest:
        rej(["g3.v.graph_digest_mismatch"], "graph digest differs from the EvidenceGraph")
        return VerifyResult(proposal, F, [], [])

    if proposal["abstain"]:
        if proposal["readings"] or proposal["coverage_candidates"]:
            rej(["g3.v.contradictory_abstain"], "abstain=true together with proposals")
        else:
            F.append(VerifierFinding(proposal_index, req.path, "ABSTAIN", ["g3.v.abstained"], proposal["reason"][:200], req.node_id))
        return VerifyResult(proposal, F, [], [])

    accepted: list[dict[str, Any]] = []
    unverified_out: list[dict[str, Any]] = []
    coverage_out: list[dict[str, Any]] = []
    ir_ids = _ir_node_ids(ir)
    cands = {c.ref: c for c in req.candidates}
    lines = _attachment_lines(sources_text)
    typed_ok: dict[str, TypedAudit] = {}
    if graph is not None:
        typed_ok = {a.edge_id: a for a in audit_typed_edges(graph, ir, sources_text)}
    span_paths = {s.source_id: s.normalized_safe_path for s in graph.sources} if graph is not None else {}

    if req.path == "node":
        if proposal["coverage_candidates"]:
            rej(["g3.v.path_mismatch"], "coverage candidates returned for a node request")
        if not proposal["readings"]:
            rej(["g3.v.empty_proposal"], "abstain=false but no readings")
        # contradictory readings: same node, different antecedents, both confident
        confident = [(i, r) for i, r in enumerate(proposal["readings"]) if r["confidence"] >= 0.5 and r.get("antecedent_ref")]
        contradictory = {i for i, r in confident for j, r2 in confident if j != i and r2["antecedent_ref"] != r["antecedent_ref"]}
        node_span = _node_span(ir, req.node_id or "")
        scope = clause_scope(ir, utterance, node_span, span_paths) if node_span else Scope((), frozenset(), (), ())
        anchors = [req.clause.text, req.context.text] + [c.text for c in req.candidates]
        for i, r in enumerate(proposal["readings"]):
            rules: list[str] = []
            ev: list[EvidenceRef] = []
            if r["node_id"] != req.node_id or r["node_id"] not in req.allowed_node_ids or r["node_id"] not in ir_ids:
                rules.append("g3.v.unknown_node")
            if r["node_id"][:1] in ("c", "p"):
                rules.append("g3.v.constraint_or_protected_target")
            ref_raw = r.get("antecedent_ref")
            ref = canonicalise_antecedent_ref(ref_raw, cands) if ref_raw else None
            cand = cands.get(ref) if ref else None
            if ref and cand is None:
                rules.append("g3.v.fabricated_ref")
            if r["relation"] == "antecedent" and not ref:
                rules.append("g3.v.missing_ref")
            if cand is not None and cand.locator is not None:
                loc = cand.locator
                gnode = None
                if graph is not None:
                    try:
                        gnode = graph.node(ref.split(":", 1)[1])
                    except KeyError:
                        rules.append("g3.v.fabricated_ref")
                if gnode is not None:
                    sp = gnode.span
                    if (sp.source_id, sp.char_start, sp.char_end) != (loc.source_id, loc.char_start, loc.char_end):
                        rules.append("g3.v.span_mismatch")
                    elif sources_text is not None:
                        st = sources_text.get(sp.source_id)
                        if st is None or st[sp.char_start:sp.char_end] != sp.text or text_digest(sp.text) != sp.digest:
                            rules.append("g3.v.span_mismatch")
                    ev.append(EvidenceRef(sp.source_id, sp.char_start, sp.char_end, sp.digest))
            if r["relation"] in ("supports", "contradicts"):
                if cand is None or cand.locator is None or cand.via_kind != r["relation"]:
                    rules.append("g3.v.unverified_entailment")
                else:
                    edge = next((e for e in graph.edges_from(req.node_id or "") if e.to_evidence_node_id == ref.split(":", 1)[1]
                                 and e.kind == r["relation"]), None) if graph is not None else None
                    audit = typed_ok.get(edge.id) if edge else None
                    if audit is None or not audit.ok or audit.expected_kind != r["relation"]:
                        rules.append("g3.v.typed_edge_forged" if audit is not None else "g3.v.unverified_entailment")
                    ev_sid = cand.locator.source_id
                    if scope.ambiguous:
                        # the clause names a file that several attached sources could be (review F9): no trusted typed reading
                        rules.append("g3.v.scope_ambiguous_source")
                    elif scope.mentioned and ev_sid not in scope.source_ids and node_span is not None:
                        if not comparison_binds(ir, utterance, req.context, node_span, scope.source_ids, ev_sid, span_paths):
                            rules.append("g3.v.cross_file_scope")
            lits = unanchored_literals(r["interpretation"], anchors)
            if lits:
                rules.append("g3.v.unanchored_literal")
            if not r["interpretation"].strip():
                rules.append("g3.v.empty_interpretation")
            if _POLICY_RE.search(r["interpretation"]):
                rules.append("g3.v.policy_vocabulary")
            if _promoted(r["interpretation"], lines):
                rules.append("g3.v.attachment_text_promoted")
            if not _is_english(r["interpretation"]):
                rules.append("g3.v.unrecognized_language")
            if i in contradictory:
                rules.append("g3.v.contradictory_readings")
            rs = RequestSpan(node_span.start, node_span.end, utterance[node_span.start:node_span.end]) if node_span else None
            if rules:
                rej(sorted(set(rules)), f"reading {i} rejected", i, r["node_id"], rs, ev)
            elif r["relation"] in VERIFIED_RELATIONS:
                binding = "antecedent_ref" if r["relation"] == "antecedent" else "typed_recomputed"
                F.append(VerifierFinding(proposal_index, "node", "ACCEPT_ADVISORY", ["g3.v.accepted_advisory"],
                                         f"advisory {r['relation']} for {r['node_id']} ({binding})", r["node_id"], i, rs, ev))
                accepted.append({**r, "antecedent_ref": ref, "proposal_index": proposal_index, "item_index": i, "advisory": True, "binding": binding,
                                 "evidence_spans": [e.__dict__ for e in ev]})
            else:
                # free-text interpretation: schema-safe, policy-clean, literals anchored — but its factual content is NOT verified
                F.append(VerifierFinding(proposal_index, "node", "ACCEPT_UNVERIFIED", ["g3.v.interpretation_unverified"],
                                         f"free-text interpretation for {r['node_id']} recorded as UNVERIFIED", r["node_id"], i, rs, ev))
                unverified_out.append({**r, "proposal_index": proposal_index, "item_index": i, "advisory": True, "status": UNVERIFIED_STATUS})
    else:  # coverage
        if proposal["readings"]:
            rej(["g3.v.path_mismatch"], "readings returned for a coverage request")
        if not proposal["coverage_candidates"]:
            rej(["g3.v.empty_proposal"], "abstain=false but no coverage candidates")
        covered = []
        for coll in (ir.graph.objectives, ir.graph.constraints, ir.graph.conditions, ir.graph.unresolved):
            covered += [(n.source_span.start, n.source_span.end) for n in coll]
        protected = [(p.source_span.start, p.source_span.end) for p in ir.graph.protected_regions]
        for i, c in enumerate(proposal["coverage_candidates"]):
            rules = []
            a, b = int(c["char_start"]), int(c["char_end"])
            if not (0 <= a < b <= len(utterance)) or utterance[a:b] != c["text"]:
                rules.append("g3.v.span_not_in_request")
            if any(s < b and a < e for s, e in covered):
                rules.append("g3.v.coverage_overlaps_node")
            if any(s <= a and b <= e for s, e in protected):
                rules.append("g3.v.coverage_inside_protected")
            if gaps is not None and not any(s <= a and b <= e for s, e in gaps):
                rules.append("g3.v.coverage_outside_gap")
            if _promoted(c["text"], lines):
                rules.append("g3.v.attachment_text_promoted")
            if _POLICY_RE.search(c.get("suggested_action") or ""):
                rules.append("g3.v.policy_vocabulary")
            if not _is_english(c["text"]):
                rules.append("g3.v.unrecognized_language")
            rs = RequestSpan(a, b, utterance[a:b]) if 0 <= a <= b <= len(utterance) else None
            if rules:
                rej(sorted(set(rules)), f"coverage candidate {i} rejected", i, None, rs)
            else:
                F.append(VerifierFinding(proposal_index, "coverage", "ACCEPT_ADVISORY", ["g3.v.coverage_candidate_unverified"],
                                         "coverage candidate recorded as UNVERIFIED (not an objective)", None, i, rs))
                coverage_out.append({**c, "status": COVERAGE_STATUS})
    return VerifyResult(proposal, F, accepted, coverage_out, unverified_out)
