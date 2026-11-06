"""RequestIR v0 — typed, span-anchored G1 IntentGraph for one user utterance (DCE-G1).

Schema id ``forge.models.request_ir.v0``. Pure data: dataclasses + JSON Schema (Draft 2020-12).

Offsets are Python ``str`` code-point indices into the *unmodified* utterance (``utterance[start:end]``). Every node
that carries ``text`` also carries ``source_span`` and ``validate(utterance)`` re-checks that the text is exactly that
slice. The IR does not store the utterance itself — ``digest`` ties it to the text it was parsed from, and
``to_dict(redact_text=True)`` yields a text-free view that is safe to log.

This module is independent of ``forge_2b.dce`` (DCE-01 RequestIR v1) and of DCS PlanIR; it imports neither.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from jsonschema import Draft202012Validator

SCHEMA_VERSION = "forge.models.request_ir.v0.1"   # v0 + conditions[], constraint.target_object/breadth, alternative_to, new verbs
PARSER_VERSION = "dce-g1r/0.5.0"   # bump whenever a rule change alters output for any frozen corpus case
# 0.5.0 (DCE-G1R3C): English-only instruction scope by default; `language_scope` field; `unsupported_language` unresolved kind

# --- documented limits (code points / counts) ------------------------------------------------------------------
MAX_UTTERANCE_CHARS = 8_000     # above: status=rejected_too_large, empty graph, no parsing performed
MAX_CLAUSES = 64                # beyond: status=partial, remainder recorded as one unresolved(truncated) node
MAX_PROTECTED_REGION_CHARS = 4_000

ACTIONS = ("enumerate", "describe", "summarize", "explain", "compare", "assess", "verify", "identify", "locate", "extract",
           "show", "count", "compute", "classify", "recommend", "translate", "transform", "modify", "create", "run", "remove",
           # v0.1
           "analyze", "inspect", "prioritize", "flag", "choose", "report", "clarify", "compose")
ACTION_CLASS = {  # informational effect class; a parsed node never executes anything
    "enumerate": "inform", "describe": "inform", "summarize": "inform", "explain": "inform", "compare": "inform",
    "identify": "inform", "locate": "inform", "extract": "inform", "show": "inform", "count": "inform", "compute": "inform",
    "classify": "inform", "translate": "inform", "transform": "inform",
    "analyze": "inform", "inspect": "inform", "flag": "inform", "report": "inform", "clarify": "inform",
    "compose": "inform",        # an artefact *in the answer* (table, example, plan, note) — not a file/system mutation
    "assess": "judge", "verify": "judge", "prioritize": "judge", "choose": "judge",
    "recommend": "propose",
    "modify": "mutate", "create": "mutate", "remove": "mutate",
    "run": "execute",
}
assert set(ACTION_CLASS) == set(ACTIONS)
ACTION_CLASSES = ("inform", "judge", "propose", "mutate", "execute")

CONSTRAINT_KINDS = ("prohibition", "requirement", "exclusion", "scope_only", "format", "locale", "cardinality", "ordering")
CONSTRAINT_SCOPES = ("objective", "request")
CONSTRAINT_BREADTHS = ("global", "narrow")    # prohibition/exclusion: whole action vs. a specific action+object pair
LINK_KINDS = ("depends_on", "alternative_to")
CONDITION_KINDS = ("if", "unless", "until", "before", "after", "else", "for_each")
UNRESOLVED_KINDS = ("ambiguous_referent", "no_recognized_action", "unsupported_script", "truncated", "vague_object", "unsupported_language")
REFERENCE_STATUSES = ("resolved_intra_utterance", "resolved_context", "unresolved")
PROTECTED_KINDS = ("code_fence", "inline_code", "quotation", "url", "path", "json_like", "yaml_like", "command_like", "attachment")
STATUSES = ("ok", "ok_with_unresolved", "partial", "empty", "rejected_too_large", "rejected_invalid_text")
LANGUAGE_HINTS = ("en", "uk", "mixed", "und")
# DCE-G1R3C: the parser interprets user-authored instructions in English only. "legacy-multilingual" is an explicit opt-in kept
# for historical regression material (deferred scope) — never the default, never used by a consumer.
LANGUAGE_SCOPES = ("en", "legacy-multilingual")
DEFAULT_LANGUAGE_SCOPE = "en"


@dataclass(frozen=True)
class ReadOnlyContext:
    """Names the caller already knows (e.g. attached file names). Never content; only used to resolve a pronoun or
    demonstrative when exactly one referent exists. Recorded in the IR as a digest."""
    referents: tuple[str, ...] = ()

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(json.dumps(sorted(self.referents), ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass
class Mention:
    text: str
    source_span: Span


@dataclass
class Reference:
    text: str
    source_span: Span
    status: str                      # REFERENCE_STATUSES
    resolved_to: Optional[str] = None  # objective / protected-region / narrow-prohibition id (intra-utterance) or context referent text


@dataclass
class Objective:
    id: str                          # o1, o2, … in source order
    action: str                      # ACTIONS
    action_class: str                # ACTION_CLASSES
    text: str                        # verbatim clause (connectives/bullets excluded)
    source_span: Span
    rule: str                        # rule id, e.g. en.imperative.enumerate
    trigger: Optional[Mention] = None
    target: Optional[Mention] = None       # verbatim remainder after the trigger, trailing constraints removed; explicit only
    output_shape: Optional[Mention] = None  # first format constraint in the clause, when explicit
    references: list[Reference] = field(default_factory=list)


@dataclass
class Constraint:
    id: str                          # c1, c2, …
    kind: str                        # CONSTRAINT_KINDS
    text: str
    source_span: Span
    rule: str
    scope: str                       # "objective" → applies_to_objective_ids non-empty; "request" → whole utterance, list empty
    applies_to_objective_ids: list[str] = field(default_factory=list)
    target_action: Optional[str] = None     # prohibition/requirement: the action the constraint is about, when recognised
    value: Optional[Mention] = None         # operand ("warnings" in "except warnings"; "JSON" in "as JSON")
    target_object: Optional[Mention] = None  # v0.1 prohibition/exclusion: the object after the forbidden verb ("removing tests")
    breadth: Optional[str] = None           # v0.1 prohibition/exclusion: "global" (action as such) or "narrow" (action+object pair)


@dataclass
class Link:
    id: str                          # l1, l2, …
    kind: str                        # LINK_KINDS; depends_on: from_id must complete after to_id; alternative_to: either/or
    from_id: str
    to_id: str
    text: str                        # the explicit marker ("then", "after that", "потім", "or")
    source_span: Span
    rule: str


@dataclass
class Condition:
    """v0.1 — an explicit subordinate qualifier ("if …", "unless …", "until …", "before -ing", "for each …", "otherwise").
    Actions named inside it are *mentions* (``mentioned_action``), never objectives; the nodes it governs are listed
    in ``applies_to_ids`` (objective, constraint or unresolved ids)."""
    id: str                          # q1, q2, …
    kind: str                        # CONDITION_KINDS
    text: str
    source_span: Span
    rule: str
    applies_to_ids: list[str] = field(default_factory=list)
    mentioned_action: Optional[str] = None   # the action lexically present in the clause (e.g. run in "before running anything")
    negates: Optional[str] = None            # kind == else: the condition id this branch is the complement of


@dataclass
class Unresolved:
    id: str                          # u1, u2, …
    kind: str                        # UNRESOLVED_KINDS
    text: str
    source_span: Span
    rule: str
    referent: Optional[str] = None   # the pronoun/demonstrative that could not be resolved
    objective_id: Optional[str] = None  # set when the unresolved reference sits inside an emitted objective


@dataclass
class ContextStatement:
    id: str                          # k1, k2, …
    text: str
    source_span: Span
    rule: str


@dataclass
class ProtectedRegion:
    id: str                          # p1, p2, …
    kind: str                        # PROTECTED_KINDS
    source_span: Span


@dataclass
class IntentGraph:
    objectives: list[Objective] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    context_statements: list[ContextStatement] = field(default_factory=list)
    protected_regions: list[ProtectedRegion] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)      # v0.1


@dataclass
class RequestIR:
    schema_version: str
    parser_version: str
    digest: str                      # sha256: of the utterance (UTF-8, surrogatepass)
    status: str                      # STATUSES
    language_hint: str               # LANGUAGE_HINTS
    utterance_chars: int             # code points
    limits: dict[str, int]
    graph: IntentGraph
    stats: dict[str, int]
    context_digest: Optional[str] = None
    language_scope: str = DEFAULT_LANGUAGE_SCOPE   # LANGUAGE_SCOPES (v0.1 additive field, DCE-G1R3C)

    # -- serialisation -----------------------------------------------------------------------------------------
    def to_dict(self, *, redact_text: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if redact_text:
            _redact(d)
        return d

    def to_json(self, *, redact_text: bool = False, **kw: Any) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("sort_keys", True)
        return json.dumps(self.to_dict(redact_text=redact_text), **kw)

    def summary(self) -> dict[str, Any]:
        """Text-free one-liner: safe for logs."""
        return {"schema_version": self.schema_version, "parser_version": self.parser_version, "digest": self.digest,
                "status": self.status, "language_hint": self.language_hint, "language_scope": self.language_scope, **self.stats}

    def __repr__(self) -> str:  # never leak utterance text through repr/logging
        return f"RequestIR({self.summary()})"

    # -- validation --------------------------------------------------------------------------------------------
    def validate(self, utterance: Optional[str] = None) -> None:
        """Full JSON-Schema validation (O(nodes), jsonschema) plus, when the utterance is given, digest and span
        round-trip checks. The parser runs ``check_spans`` on every call; the schema pass is opt-in (``strict=True``)
        because the dataclasses already fix the shape and the schema walk dominates latency."""
        doc = self.to_dict()
        errors = sorted(VALIDATOR.iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"RequestIR schema: {errors[0].message} at /{'/'.join(map(str, errors[0].path))}")
        if utterance is not None:
            self.check_spans(utterance)

    def check_spans(self, utterance: str) -> None:
        """Cheap integrity check: digest matches and every node text is exactly its source slice."""
        if self.digest != utterance_digest(utterance):
            raise ValueError("RequestIR digest does not match utterance")
        n = len(utterance)
        for node in _spanned_objs(self.graph):
            s = node.source_span
            if not (0 <= s.start <= s.end <= n):
                raise ValueError(f"span out of range: {s}")
            text = getattr(node, "text", None)
            if text is not None and utterance[s.start:s.end] != text:
                raise ValueError(f"text does not round-trip to the utterance slice at {s}")


def utterance_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _redact(obj: Any) -> None:
    if isinstance(obj, dict):
        for k in list(obj):
            if k in ("text", "referent", "resolved_to"):
                obj[k] = None if obj[k] is None else "<redacted>"
            else:
                _redact(obj[k])
    elif isinstance(obj, list):
        for x in obj:
            _redact(x)


def _spanned_objs(graph: "IntentGraph"):
    for o in graph.objectives:
        yield o
        for sub in (o.trigger, o.target, o.output_shape):
            if sub is not None:
                yield sub
        yield from o.references
    for c in graph.constraints:
        yield c
        for sub in (c.value, c.target_object):
            if sub is not None:
                yield sub
    yield from graph.links
    yield from graph.unresolved
    yield from graph.context_statements
    yield from graph.protected_regions
    yield from graph.conditions


# --- JSON Schema ---------------------------------------------------------------------------------------------------
_SPAN = {"type": "object", "required": ["start", "end"], "additionalProperties": False,
         "properties": {"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 0}}}
_MENTION = {"type": "object", "required": ["text", "source_span"], "additionalProperties": False,
            "properties": {"text": {"type": "string"}, "source_span": _SPAN}}
_OPT_MENTION = {"oneOf": [{"type": "null"}, _MENTION]}
_ID = lambda prefix: {"type": "string", "pattern": rf"^{prefix}[0-9]+$"}  # noqa: E731
_REFERENCE = {"type": "object", "required": ["text", "source_span", "status", "resolved_to"], "additionalProperties": False,
              "properties": {"text": {"type": "string"}, "source_span": _SPAN, "status": {"enum": list(REFERENCE_STATUSES)},
                             "resolved_to": {"type": ["string", "null"]}}}
_OBJECTIVE = {"type": "object", "additionalProperties": False,
              "required": ["id", "action", "action_class", "text", "source_span", "rule", "trigger", "target", "output_shape", "references"],
              "properties": {"id": _ID("o"), "action": {"enum": list(ACTIONS)}, "action_class": {"enum": list(ACTION_CLASSES)},
                             "text": {"type": "string", "minLength": 1}, "source_span": _SPAN, "rule": {"type": "string", "minLength": 1},
                             "trigger": _OPT_MENTION, "target": _OPT_MENTION, "output_shape": _OPT_MENTION,
                             "references": {"type": "array", "items": _REFERENCE}}}
_CONSTRAINT = {"type": "object", "additionalProperties": False,
               "required": ["id", "kind", "text", "source_span", "rule", "scope", "applies_to_objective_ids", "target_action", "value",
                            "target_object", "breadth"],
               "properties": {"id": _ID("c"), "kind": {"enum": list(CONSTRAINT_KINDS)}, "text": {"type": "string", "minLength": 1},
                              "source_span": _SPAN, "rule": {"type": "string"}, "scope": {"enum": list(CONSTRAINT_SCOPES)},
                              "applies_to_objective_ids": {"type": "array", "items": _ID("o")},
                              "target_action": {"oneOf": [{"type": "null"}, {"enum": list(ACTIONS)}]}, "value": _OPT_MENTION,
                              "target_object": _OPT_MENTION, "breadth": {"oneOf": [{"type": "null"}, {"enum": list(CONSTRAINT_BREADTHS)}]}}}
_LINK = {"type": "object", "additionalProperties": False, "required": ["id", "kind", "from_id", "to_id", "text", "source_span", "rule"],
         "properties": {"id": _ID("l"), "kind": {"enum": list(LINK_KINDS)}, "from_id": _ID("o"), "to_id": _ID("o"),
                        "text": {"type": "string"}, "source_span": _SPAN, "rule": {"type": "string"}}}
_NODE_ID = {"type": "string", "pattern": r"^[ocu][0-9]+$"}
_CONDITION = {"type": "object", "additionalProperties": False,
              "required": ["id", "kind", "text", "source_span", "rule", "applies_to_ids", "mentioned_action", "negates"],
              "properties": {"id": _ID("q"), "kind": {"enum": list(CONDITION_KINDS)}, "text": {"type": "string", "minLength": 1}, "source_span": _SPAN,
                             "rule": {"type": "string"}, "applies_to_ids": {"type": "array", "items": _NODE_ID},
                             "mentioned_action": {"oneOf": [{"type": "null"}, {"enum": list(ACTIONS)}]}, "negates": {"oneOf": [{"type": "null"}, _ID("q")]}}}
_UNRESOLVED = {"type": "object", "additionalProperties": False, "required": ["id", "kind", "text", "source_span", "rule", "referent", "objective_id"],
               "properties": {"id": _ID("u"), "kind": {"enum": list(UNRESOLVED_KINDS)}, "text": {"type": "string"}, "source_span": _SPAN,
                              "rule": {"type": "string"}, "referent": {"type": ["string", "null"]}, "objective_id": {"oneOf": [{"type": "null"}, _ID("o")]}}}
_CONTEXT = {"type": "object", "additionalProperties": False, "required": ["id", "text", "source_span", "rule"],
            "properties": {"id": _ID("k"), "text": {"type": "string"}, "source_span": _SPAN, "rule": {"type": "string"}}}
_PROTECTED = {"type": "object", "additionalProperties": False, "required": ["id", "kind", "source_span"],
              "properties": {"id": _ID("p"), "kind": {"enum": list(PROTECTED_KINDS)}, "source_span": _SPAN}}
STAT_KEYS = ("clauses", "objectives", "constraints", "links", "unresolved", "unresolved_references", "context_statements",
             "protected_regions", "conditions", "chars_covered", "chars_total")
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": SCHEMA_VERSION,
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "parser_version", "digest", "status", "language_hint", "utterance_chars", "limits", "graph", "stats", "context_digest"],
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "parser_version": {"type": "string", "pattern": r"^dce-g1r?/\d+\.\d+\.\d+$"},
        "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "status": {"enum": list(STATUSES)},
        "language_hint": {"enum": list(LANGUAGE_HINTS)},
        "language_scope": {"enum": list(LANGUAGE_SCOPES)},
        "utterance_chars": {"type": "integer", "minimum": 0},
        "limits": {"type": "object", "additionalProperties": False, "required": ["max_utterance_chars", "max_clauses"],
                   "properties": {"max_utterance_chars": {"type": "integer"}, "max_clauses": {"type": "integer"}}},
        "graph": {"type": "object", "additionalProperties": False,
                  "required": ["objectives", "constraints", "links", "unresolved", "context_statements", "protected_regions", "conditions"],
                  "properties": {"objectives": {"type": "array", "items": _OBJECTIVE}, "constraints": {"type": "array", "items": _CONSTRAINT},
                                 "links": {"type": "array", "items": _LINK}, "unresolved": {"type": "array", "items": _UNRESOLVED},
                                 "context_statements": {"type": "array", "items": _CONTEXT},
                                 "protected_regions": {"type": "array", "items": _PROTECTED},
                                 "conditions": {"type": "array", "items": _CONDITION}}},
        "stats": {"type": "object", "additionalProperties": False, "required": list(STAT_KEYS),
                  "properties": {k: {"type": "integer", "minimum": 0} for k in STAT_KEYS}},
        "context_digest": {"oneOf": [{"type": "null"}, {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}]},
    },
}
VALIDATOR = Draft202012Validator(SCHEMA)
