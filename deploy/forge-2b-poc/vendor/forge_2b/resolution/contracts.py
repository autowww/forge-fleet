"""DCE-G3 — immutable contracts for selective small-model graph resolution.

Four versioned documents, all ``additionalProperties: false``:

* ``ResolutionRequest``  — what the model is shown (bounded slice; digests of the frozen RequestIR / EvidenceGraph).
* ``ResolutionProposal`` — what the model returned, parsed and schema-checked (readings, coverage candidates, abstain).
* ``VerifierFinding``    — the deterministic disposition per reading / coverage candidate
  (ACCEPT_ADVISORY | ACCEPT_UNVERIFIED | REJECT | ABSTAIN).
* ``ResolutionOverlay``  — ``forge.models.resolution.v0.2``: a sidecar that *references* G1/G2 node ids. It never carries
  authorization vocabulary, never mutates the RequestIR or the EvidenceGraph, and every accepted item is advisory.
  v0.2 (G3H) splits ``accepted_readings`` (relation deterministically bound, with ``binding``) from ``unverified_readings``
  (free-text interpretations, ``status: UNVERIFIED``) and adds the call/input budget telemetry.

Nothing in this module calls a model or touches the network.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from jsonschema import Draft202012Validator

RESOLUTION_SCHEMA_VERSION = "forge.models.resolution.v0.2"
REQUEST_SCHEMA_VERSION = "forge.models.resolution_request.v0.1"
PROPOSAL_SCHEMA_VERSION = "forge.models.resolution_proposal.v0.1"
RESOLVER_VERSION = "dce-g3/0.1.3"
VERIFIER_VERSION = "dce-g3-verifier/0.1.3"

PATHS = ("node", "coverage")
# ACCEPT_ADVISORY: the *relation* was verified deterministically (antecedent ref rebinds; typed edge recomputed from literal spans).
# ACCEPT_UNVERIFIED (G3H / review F10): schema-safe free text whose factual content nothing checked — recorded apart, never evidence-backed.
DISPOSITIONS = ("ACCEPT_ADVISORY", "ACCEPT_UNVERIFIED", "REJECT", "ABSTAIN")
RELATIONS = ("antecedent", "interpretation", "supports", "contradicts")
VERIFIED_RELATIONS = ("antecedent", "supports", "contradicts")     # relations with a deterministic binding check
COVERAGE_STATUS = "UNVERIFIED"
UNVERIFIED_STATUS = "UNVERIFIED"
BINDINGS = ("antecedent_ref", "typed_recomputed")                  # accepted_readings[].binding — what exactly was verified
UNCERTAINTY_REASONS = ("ambiguous_referent", "vague_object", "no_recognized_action", "unresolved_reference", "coverage_gap")

# Keys that may never appear anywhere in a request, proposal, finding or overlay document (checked recursively).
FORBIDDEN_KEYS = ("allow", "allowed", "authorize", "authorized", "authorization", "approve", "approved", "execute", "executed",
                  "schedule", "scheduled", "tool_call", "tool_calls", "permission", "permissions", "policy", "decision",
                  "resolved_by", "run", "action_plan")

NOTES = (
    "advisory only: accepted readings are candidate interpretations for inspection, never executable objectives",
    "the RequestIR and the EvidenceGraph referenced by digest are immutable inputs; this overlay adds nothing to them",
    "coverage candidates are UNVERIFIED instruction spans; they are not objectives and do not widen or narrow any constraint",
    "no authorization semantics: this document cannot allow, schedule or execute anything",
    "unverified readings are free text whose factual content was not checked against any source; consumers must not treat them as evidence",
    "estimated_input_tokens is a chars/4 estimate enforced as a character bound; input_tokens is what the backend measured",
)


# ----------------------------------------------------------------------------------------------------------- records ---
@dataclass(frozen=True)
class RequestSpan:
    char_start: int
    char_end: int
    text: str


@dataclass(frozen=True)
class Locator:
    source_id: str
    path: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class Candidate:
    """Something the model may point at: a request node, an evidence node or a whole source."""
    ref: str                              # "node:<id>" | "evidence:<e-id>" | "source:<s-id>"
    text: str                             # bounded excerpt (request node text / evidence span text / path)
    locator: Optional[Locator] = None     # evidence only
    via_kind: Optional[str] = None        # G2 edge kind that produced this candidate (mentions/constrains/supports/contradicts)
    via_rule: Optional[str] = None


@dataclass(frozen=True)
class Budget:
    max_input_tokens: int = 512
    max_output_tokens: int = 128
    max_output_chars: int = 2048
    retries: int = 1
    max_node_calls: int = 4
    max_coverage_calls: int = 1
    max_total_calls: int = 5


@dataclass
class ResolutionRequest:
    schema_version: str
    request_digest: str                   # sha256 of the utterance (RequestIR.digest)
    ir_digest: str                        # sha256 of RequestIR canonical JSON
    graph_digest: str                     # EvidenceGraph.graph_digest ("" when no graph)
    path: str                             # PATHS
    uncertainty_reason: str               # UNCERTAINTY_REASONS
    clause: RequestSpan
    context: RequestSpan
    allowed_node_ids: list[str]
    candidates: list[Candidate]
    warnings: list[str]
    budget: Budget
    prompt_version: str
    node_id: Optional[str] = None
    node_kind: Optional[str] = None
    prompt_digest: str = ""               # sha256 of the exact prompt text

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Reading:
    node_id: str
    relation: str                         # RELATIONS
    interpretation: str                   # <= 240 chars, English
    confidence: float                     # advisory 0..1
    antecedent_ref: Optional[str] = None  # "node:..." | "evidence:..." | "source:..." (must be one of request.candidates)


@dataclass(frozen=True)
class CoverageCandidate:
    char_start: int
    char_end: int
    text: str
    confidence: float
    status: str = COVERAGE_STATUS
    suggested_action: Optional[str] = None


@dataclass
class ResolutionProposal:
    schema_version: str
    abstain: bool
    reason: str
    readings: list[Reading] = field(default_factory=list)
    coverage_candidates: list[CoverageCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceRef:
    source_id: str
    char_start: int
    char_end: int
    text_digest: str


@dataclass
class VerifierFinding:
    proposal_index: int
    path: str
    disposition: str                      # DISPOSITIONS
    rule_ids: list[str]
    detail: str
    node_id: Optional[str] = None
    item_index: Optional[int] = None      # reading / coverage index inside the proposal
    request_span: Optional[RequestSpan] = None
    evidence_spans: list[EvidenceRef] = field(default_factory=list)
    advisory: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResolutionOverlay:
    schema_version: str
    version: str
    verifier_version: str
    request_digest: str
    ir_digest: str
    graph_digest: str
    backend: dict[str, Any]               # model_id, kind, runtime, prompt_version, settings (no secrets)
    selection: dict[str, Any]             # decision-table outcome
    requests: list[dict[str, Any]]        # ResolutionRequest.to_dict() minus nothing (bounded by construction)
    proposals: list[dict[str, Any]]       # parsed proposals (or {"raw_rejected": true, ...}) one per request
    findings: list[dict[str, Any]]
    accepted_readings: list[dict[str, Any]]      # readings with ACCEPT_ADVISORY (relation deterministically bound), flattened for consumers
    coverage_candidates: list[dict[str, Any]]    # all UNVERIFIED
    unverified_readings: list[dict[str, Any]]    # readings with ACCEPT_UNVERIFIED — free text, status UNVERIFIED, never evidence-backed
    warnings_carried: list[dict[str, Any]]       # G2 warnings copied verbatim
    telemetry: dict[str, Any]
    notes: list[str]
    overlay_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw: Any) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("sort_keys", True)
        return json.dumps(self.to_dict(), **kw)


# ----------------------------------------------------------------------------------------------------------- schemas ---
def _obj(props: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props,
            "required": required if required is not None else sorted(props)}


_STR = {"type": "string"}
_INT0 = {"type": "integer", "minimum": 0}
_CONF = {"type": "number", "minimum": 0, "maximum": 1}
_NSTR = {"type": ["string", "null"]}
_SPAN = _obj({"char_start": _INT0, "char_end": _INT0, "text": _STR})
_LOCATOR = _obj({"source_id": _STR, "path": _STR, "char_start": _INT0, "char_end": _INT0})
_CANDIDATE = _obj({"ref": {"type": "string", "pattern": r"^(node|evidence|source):[A-Za-z0-9_\-]+$"}, "text": {"type": "string", "maxLength": 400},
                   "locator": {"oneOf": [_LOCATOR, {"type": "null"}]}, "via_kind": _NSTR, "via_rule": _NSTR})
_BUDGET = _obj({k: {"type": "integer", "minimum": 0} for k in Budget.__dataclass_fields__})

REQUEST_SCHEMA = _obj({
    "schema_version": {"const": REQUEST_SCHEMA_VERSION}, "request_digest": _STR, "ir_digest": _STR, "graph_digest": _STR,
    "path": {"enum": list(PATHS)}, "uncertainty_reason": {"enum": list(UNCERTAINTY_REASONS)}, "clause": _SPAN, "context": _SPAN,
    "allowed_node_ids": {"type": "array", "items": _STR}, "candidates": {"type": "array", "items": _CANDIDATE, "maxItems": 32},
    "warnings": {"type": "array", "items": _STR}, "budget": _BUDGET, "prompt_version": _STR, "node_id": _NSTR, "node_kind": _NSTR,
    "prompt_digest": _STR,
})

_READING = _obj({"node_id": _STR, "relation": {"enum": list(RELATIONS)}, "interpretation": {"type": "string", "maxLength": 240},
                 "confidence": _CONF, "antecedent_ref": _NSTR}, required=["node_id", "relation", "interpretation", "confidence"])
_COVERAGE = _obj({"char_start": _INT0, "char_end": _INT0, "text": {"type": "string", "maxLength": 400}, "confidence": _CONF,
                  "status": {"const": COVERAGE_STATUS}, "suggested_action": _NSTR},
                 required=["char_start", "char_end", "text", "confidence"])

PROPOSAL_SCHEMA = _obj({
    "schema_version": {"const": PROPOSAL_SCHEMA_VERSION}, "abstain": {"type": "boolean"}, "reason": {"type": "string", "maxLength": 400},
    "readings": {"type": "array", "items": _READING, "maxItems": 8},
    "coverage_candidates": {"type": "array", "items": _COVERAGE, "maxItems": 8},
}, required=["abstain", "reason"])

# What the *model* is allowed to emit (no schema_version required; we add it). Same shape otherwise.
MODEL_OUTPUT_SCHEMA = _obj({
    "abstain": {"type": "boolean"}, "reason": {"type": "string", "maxLength": 400},
    "readings": {"type": "array", "items": _READING, "maxItems": 8},
    "coverage_candidates": {"type": "array", "items": _obj({"char_start": _INT0, "char_end": _INT0, "text": {"type": "string", "maxLength": 400},
                                                            "confidence": _CONF, "suggested_action": _NSTR},
                                                           required=["char_start", "char_end", "text", "confidence"]), "maxItems": 8},
}, required=["abstain", "reason"])

_EVREF = _obj({"source_id": _STR, "char_start": _INT0, "char_end": _INT0, "text_digest": _STR})
FINDING_SCHEMA = _obj({
    "proposal_index": _INT0, "path": {"enum": list(PATHS)}, "disposition": {"enum": list(DISPOSITIONS)},
    "rule_ids": {"type": "array", "items": {"type": "string", "pattern": r"^g3\.v\.[a-z_]+$"}, "minItems": 1},
    "detail": _STR, "node_id": _NSTR, "item_index": {"type": ["integer", "null"]}, "request_span": {"oneOf": [_SPAN, {"type": "null"}]},
    "evidence_spans": {"type": "array", "items": _EVREF}, "advisory": {"const": True},
})

OVERLAY_SCHEMA = _obj({
    "schema_version": {"const": RESOLUTION_SCHEMA_VERSION}, "version": _STR, "verifier_version": _STR,
    "request_digest": _STR, "ir_digest": _STR, "graph_digest": _STR,
    "backend": _obj({"kind": {"enum": ["none", "null", "recorded", "openai_compatible"]}, "model_id": _STR, "runtime": {"type": "object"},
                     "prompt_version": _STR, "settings": {"type": "object"}}),
    "selection": {"type": "object"},
    "requests": {"type": "array", "items": REQUEST_SCHEMA},
    "proposals": {"type": "array", "items": {"type": "object"}},
    "findings": {"type": "array", "items": FINDING_SCHEMA},
    "accepted_readings": {"type": "array", "items": _obj({**_READING["properties"], "proposal_index": _INT0, "item_index": _INT0, "advisory": {"const": True},
                                                          "binding": {"enum": list(BINDINGS)}, "evidence_spans": {"type": "array", "items": _EVREF}},
                                                         required=["node_id", "relation", "interpretation", "confidence", "proposal_index", "item_index",
                                                                   "advisory", "binding", "evidence_spans"])},
    "coverage_candidates": {"type": "array", "items": _COVERAGE},
    "unverified_readings": {"type": "array", "items": _obj({**_READING["properties"], "proposal_index": _INT0, "item_index": _INT0, "advisory": {"const": True},
                                                            "status": {"const": UNVERIFIED_STATUS}},
                                                           required=["node_id", "relation", "interpretation", "confidence", "proposal_index", "item_index",
                                                                     "advisory", "status"])},
    "warnings_carried": {"type": "array", "items": {"type": "object"}},
    "telemetry": {"type": "object"},
    "notes": {"type": "array", "items": _STR, "minItems": len(NOTES)},
    "overlay_digest": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
})

_V_REQUEST = Draft202012Validator(REQUEST_SCHEMA)
_V_PROPOSAL = Draft202012Validator(PROPOSAL_SCHEMA)
_V_MODEL = Draft202012Validator(MODEL_OUTPUT_SCHEMA)
_V_OVERLAY = Draft202012Validator(OVERLAY_SCHEMA)


# ----------------------------------------------------------------------------------------------------------- helpers ---
def digest_of(body: Any) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def forbidden_keys_in(doc: Any, path: str = "$") -> list[str]:
    out: list[str] = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k.lower() in FORBIDDEN_KEYS:
                out.append(f"{path}.{k}")
            out.extend(forbidden_keys_in(v, f"{path}.{k}"))
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            out.extend(forbidden_keys_in(v, f"{path}[{i}]"))
    return out


def _schema_errors(validator: Draft202012Validator, doc: Any, label: str) -> list[str]:
    return [f"{label}: {e.message} at /{'/'.join(map(str, e.path))}" for e in sorted(validator.iter_errors(doc), key=lambda e: list(e.path))]


def validate_request(doc: dict[str, Any]) -> list[str]:
    return _schema_errors(_V_REQUEST, doc, "request") + [f"request: forbidden key {p}" for p in forbidden_keys_in(doc)]


def validate_model_output(doc: Any) -> list[str]:
    if not isinstance(doc, dict):
        return ["model_output: not a JSON object"]
    return _schema_errors(_V_MODEL, doc, "model_output") + [f"model_output: forbidden key {p}" for p in forbidden_keys_in(doc)]


def validate_proposal(doc: dict[str, Any]) -> list[str]:
    return _schema_errors(_V_PROPOSAL, doc, "proposal") + [f"proposal: forbidden key {p}" for p in forbidden_keys_in(doc)]


def validate_overlay(doc: dict[str, Any]) -> list[str]:
    """Structural validation of a ResolutionOverlay: schema, forbidden keys, digest, internal consistency
    (every accepted reading has an ACCEPT_ADVISORY finding; every coverage candidate is UNVERIFIED; counts agree)."""
    errs = _schema_errors(_V_OVERLAY, doc, "overlay")
    errs += [f"overlay: forbidden key {p}" for p in forbidden_keys_in(doc)]
    if errs:
        return errs
    body = {k: v for k, v in doc.items() if k != "overlay_digest"}
    if digest_of(body) != doc["overlay_digest"]:
        errs.append("overlay: overlay_digest does not match the document")
    for n in NOTES:
        if n not in doc["notes"]:
            errs.append(f"overlay: missing note {n[:40]!r}")
    accepted = {(f["proposal_index"], f["item_index"]) for f in doc["findings"] if f["disposition"] == "ACCEPT_ADVISORY" and f["path"] == "node"}
    unverified = {(f["proposal_index"], f["item_index"]) for f in doc["findings"] if f["disposition"] == "ACCEPT_UNVERIFIED" and f["path"] == "node"}
    for r in doc["accepted_readings"]:
        if (r.get("proposal_index"), r.get("item_index")) not in accepted:
            errs.append(f"overlay: accepted reading without ACCEPT_ADVISORY finding: {r.get('proposal_index')}/{r.get('item_index')}")
        if r.get("advisory") is not True:
            errs.append("overlay: accepted reading not marked advisory")
        if r.get("relation") not in VERIFIED_RELATIONS:
            errs.append(f"overlay: accepted reading with unverifiable relation {r.get('relation')!r} (belongs in unverified_readings)")
        if (r.get("relation") == "antecedent") != (r.get("binding") == "antecedent_ref"):
            errs.append("overlay: accepted reading binding does not match its relation")
    for r in doc["unverified_readings"]:
        if (r.get("proposal_index"), r.get("item_index")) not in unverified:
            errs.append(f"overlay: unverified reading without ACCEPT_UNVERIFIED finding: {r.get('proposal_index')}/{r.get('item_index')}")
        if r.get("status") != UNVERIFIED_STATUS:
            errs.append("overlay: unverified reading not marked UNVERIFIED")
    if len(unverified) != len(doc["unverified_readings"]) or len(accepted) != len(doc["accepted_readings"]):
        errs.append("overlay: accepted/unverified reading counts differ from their findings")
    for c in doc["coverage_candidates"]:
        if c.get("status") != COVERAGE_STATUS:
            errs.append("overlay: coverage candidate not UNVERIFIED")
    if len(doc["proposals"]) != len(doc["requests"]):
        errs.append("overlay: proposals and requests count differ")
    t = doc["telemetry"]
    if t.get("calls_made", 0) > t.get("calls_planned", 0) + t.get("retries", 0):
        errs.append("overlay: more calls made than planned plus retries")
    caps = [r["budget"]["max_total_calls"] for r in doc["requests"]]
    if caps and t.get("calls_made", 0) > min(caps):
        errs.append("overlay: calls_made exceeds max_total_calls (actual backend attempts, retries included)")
    return errs
