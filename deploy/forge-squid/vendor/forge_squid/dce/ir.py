"""RequestIR v1 — deterministic, span-anchored representation of a user's request (DCE-01).

Pure data: dataclasses + JSON schema. Every goal, constraint and target carries a character span of the *original*
prompt; the prompt hash is immutable so an IR can always be checked against the text it was parsed from.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

IR_VERSION = "forge-squid.request-ir.v1"

OPERATORS = ("list", "inspect", "extract", "count", "find", "compare", "reconcile", "summarize", "validate", "recommend", "transform", "audit")
CONSTRAINT_KINDS = ("negation", "exclusion", "scope", "order", "precondition", "output_shape", "time", "quantity")
TARGET_KINDS = ("file", "file_group", "attachment", "entity", "field", "selector")
ROUTES = ("housekeeping", "unsupported", "graph_candidate", "manifest", "scan", "overview", "qa", "qa_multi_source")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    text: str


@dataclass
class Target:
    kind: str                 # TARGET_KINDS
    value: str                # path, group label, entity text, …
    span: Span
    candidates: list[str] = field(default_factory=list)   # >1 when the mention is ambiguous among attached files
    resolved: bool = True


@dataclass
class Constraint:
    kind: str                 # CONSTRAINT_KINDS
    value: str
    span: Span
    applies_to: list[str] = field(default_factory=list)   # goal ids; empty = request-wide


@dataclass
class Goal:
    id: str
    operator: str             # OPERATORS
    span: Span
    polarity: str = "positive"
    order_index: int = 0
    depends_on: list[str] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    trigger: str = ""         # the lexicon token that fired (for rationale)


@dataclass
class Unresolved:
    span: Span
    reason: str               # no_operator | out_of_scope_verb | imperative_unparsed


@dataclass
class Ambiguity:
    span: Span
    kind: str                 # target_ambiguous | recency_unresolved | referent_unclear
    detail: str
    candidates: list[str] = field(default_factory=list)


@dataclass
class AttachmentRef:
    name: str
    kind: str                 # zip | text
    files: list[str] = field(default_factory=list)


@dataclass
class Routing:
    route: str                # ROUTES
    rationale: list[str] = field(default_factory=list)
    llm_expected: bool = False


@dataclass
class RequestIR:
    version: str
    prompt_sha256: str
    text: str
    language_hint: str
    goals: list[Goal]
    constraints: list[Constraint]
    attachments: list[AttachmentRef]
    unresolved: list[Unresolved]
    ambiguities: list[Ambiguity]
    smalltalk: list[Span]
    premises: list[Span]      # declarative context clauses ("The README says 2 …"); never goals, their mentions feed the next goal's targets
    routing: Routing
    coverage: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw: Any) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("sort_keys", True)
        return json.dumps(self.to_dict(), **kw)

    def validate(self) -> None:
        errors = sorted(VALIDATOR.iter_errors(self.to_dict()), key=lambda e: list(e.path))
        if errors:
            raise ValueError(f"RequestIR schema: {errors[0].message} at {'/'.join(map(str, errors[0].path))}")
        if self.prompt_sha256 != prompt_hash(self.text):
            raise ValueError("RequestIR prompt hash does not match text")
        for g in self.goals:
            if self.text[g.span.start:g.span.end] != g.span.text:
                raise ValueError(f"goal {g.id} span does not point into the prompt")


def prompt_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


_SPAN = {"type": "object", "required": ["start", "end", "text"], "additionalProperties": False,
         "properties": {"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 0}, "text": {"type": "string"}}}
_TARGET = {"type": "object", "required": ["kind", "value", "span", "candidates", "resolved"], "additionalProperties": False,
           "properties": {"kind": {"enum": list(TARGET_KINDS)}, "value": {"type": "string"}, "span": _SPAN,
                          "candidates": {"type": "array", "items": {"type": "string"}}, "resolved": {"type": "boolean"}}}
_CONSTRAINT = {"type": "object", "required": ["kind", "value", "span", "applies_to"], "additionalProperties": False,
               "properties": {"kind": {"enum": list(CONSTRAINT_KINDS)}, "value": {"type": "string"}, "span": _SPAN,
                              "applies_to": {"type": "array", "items": {"type": "string"}}}}
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["version", "prompt_sha256", "text", "language_hint", "goals", "constraints", "attachments", "unresolved", "ambiguities",
                 "smalltalk", "premises", "routing", "coverage"],
    "properties": {
        "version": {"const": IR_VERSION},
        "prompt_sha256": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "text": {"type": "string"},
        "language_hint": {"type": "string", "pattern": "^[a-z]{2,3}(-[a-z]+)?$"},
        "goals": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "operator", "span", "polarity", "order_index", "depends_on", "targets", "constraints", "trigger"],
            "properties": {"id": {"type": "string", "pattern": "^g[0-9]+$"}, "operator": {"enum": list(OPERATORS)}, "span": _SPAN,
                           "polarity": {"enum": ["positive", "negative"]}, "order_index": {"type": "integer", "minimum": 0},
                           "depends_on": {"type": "array", "items": {"type": "string"}}, "targets": {"type": "array", "items": _TARGET},
                           "constraints": {"type": "array", "items": _CONSTRAINT}, "trigger": {"type": "string"}}}},
        "constraints": {"type": "array", "items": _CONSTRAINT},
        "attachments": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "kind", "files"],
                                                   "properties": {"name": {"type": "string"}, "kind": {"enum": ["zip", "text"]},
                                                                  "files": {"type": "array", "items": {"type": "string"}}}}},
        "unresolved": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["span", "reason"],
                                                  "properties": {"span": _SPAN, "reason": {"enum": ["no_operator", "out_of_scope_verb", "imperative_unparsed"]}}}},
        "ambiguities": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["span", "kind", "detail", "candidates"],
                                                   "properties": {"span": _SPAN, "kind": {"enum": ["target_ambiguous", "recency_unresolved", "referent_unclear"]},
                                                                  "detail": {"type": "string"}, "candidates": {"type": "array", "items": {"type": "string"}}}}},
        "smalltalk": {"type": "array", "items": _SPAN},
        "premises": {"type": "array", "items": _SPAN},
        "routing": {"type": "object", "additionalProperties": False, "required": ["route", "rationale", "llm_expected"],
                    "properties": {"route": {"enum": list(ROUTES)}, "rationale": {"type": "array", "items": {"type": "string"}}, "llm_expected": {"type": "boolean"}}},
        "coverage": {"type": "object", "additionalProperties": False, "required": ["clauses", "clauses_with_goal", "unresolved_clauses", "chars_covered", "chars_total"],
                     "properties": {k: {"type": "integer", "minimum": 0} for k in ("clauses", "clauses_with_goal", "unresolved_clauses", "chars_covered", "chars_total")}},
    },
}
VALIDATOR = Draft202012Validator(SCHEMA)
