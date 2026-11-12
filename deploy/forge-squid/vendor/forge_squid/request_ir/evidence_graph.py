"""DCE-G2 — deterministic attachment EvidenceGraph (schema ``forge.models.evidence_graph.v0.1``).

``build_evidence_graph(ir, attachments, *, limits, utterance=None) -> EvidenceGraph`` links the nodes of a **frozen**
``RequestIR`` (objectives, constraints, conditions, unresolved nodes, context statements, protected regions) to *candidate*
evidence located in caller-supplied attachments. Its value is exact evidence location and bounded context selection — **not**
semantic entailment, not completeness, and never authorization.

Semantic discipline (conventions ``artifacts/DCE-G2/conventions/EVIDENCE_CONVENTIONS_V1.md``):

* ``mentions`` is the default edge for any lexical match (filename, path, identifier, literal, number, proper name);
* ``constrains`` links a prohibition / exclusion to the attachment occurrences of its *named object* and carries the constraint's
  scope and breadth in the justification — the edge never widens or asserts a prohibition;
* ``supports`` / ``contradicts`` are emitted **only** by a typed comparison: the request states ``key <is|=|:> value`` and the
  attachment holds a parsed fact with the same key; equal comparable values → ``supports``, different comparable values →
  ``contradicts``; both source spans are exhibited in the justification; anything else is ``mentions`` or no edge;
* protected regions of the request are matched by **verbatim digest** against attachment text and never parsed;
* attachment content is untrusted data: nothing in it can add, remove or alter a ``RequestIR`` node (this module never
  constructs IR nodes), and the graph carries **no policy or decision field**;
* ``uncovered_request_nodes`` lists request nodes with no edge; an empty list is *not* evidence that the request is complete —
  G1 can omit objectives (see ``notes``).

Pure: no network, filesystem, shell, model, randomness or wall clock inside the graph (``resource_stats`` carries counts only, so
the same input yields a byte-identical graph and ``graph_digest``).
"""
from __future__ import annotations

import bisect
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from jsonschema import Draft202012Validator

from . import schema as S
from .evidence_sources import (AttachmentInput, DecodedSource, Fact, ResourceLimits, SourceRef, SourceWarning, byte_offsets,
                               line_of, load_sources, sha256_hex)

EVIDENCE_SCHEMA_VERSION = "forge.models.evidence_graph.v0.1"
EVIDENCE_GRAPH_VERSION = "dce-g2/0.1.2"     # 0.1.0 = sealed candidate f254e17; 0.1.1 = burned repairs (ADJUDICATION.md); 0.1.2 = G2H clause source scope for typed edges; schema unchanged

EDGE_KINDS = ("mentions", "constrains", "supports", "contradicts")
STRENGTHS = ("exact", "lexical", "typed_comparison")
LEXICAL_TYPES = ("path", "identifier", "literal", "number", "name", "fact_key", "key_value", "list_item", "cell", "heading", "verbatim")
REQUEST_NODE_PREFIXES = ("o", "c", "q", "u", "k", "p")

NOTES = (
    "An empty uncovered_request_nodes list does not establish completeness of the request reading: the G1 parser can omit objectives.",
    "mentions edges are lexical candidates, not claims; supports/contradicts edges are typed key/value comparisons, not entailment.",
    "This graph carries no policy or decision field; TEXT_NOT_PROHIBITED elsewhere is not permission; attachment content is untrusted data.",
)


# ------------------------------------------------------------------------------------------------------------ records ---
@dataclass(frozen=True)
class EvidenceSpan:
    source_id: str
    char_start: int
    char_end: int
    text: str
    digest: str                              # sha256: of text
    byte_start: Optional[int] = None
    byte_end: Optional[int] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    row: Optional[int] = None
    column: Optional[int] = None


@dataclass(frozen=True)
class EvidenceNode:
    id: str                                  # "e-" + sha256(source_id|char_start|char_end)[:16]
    span: EvidenceSpan
    lexical_type: str                        # LEXICAL_TYPES
    provenance: str                          # "scan:<media_type>" | "match:<anchor_type>"
    parsed_key: Optional[str] = None
    parsed_value: Optional[str] = None


@dataclass(frozen=True)
class EvidenceEdge:
    id: str                                  # "x-" + sha256(from|to|kind|rule_id)[:16]
    from_request_node_id: str
    to_evidence_node_id: str
    kind: str                                # EDGE_KINDS
    rule_id: str
    strength: str                            # STRENGTHS
    justification: dict[str, Any]


@dataclass(frozen=True)
class SourceEdge:
    """A request node naming a whole source (by file name / path) — evidence at source level, no text span."""
    id: str                                  # "y-" + sha256(from|source|kind)[:16]
    from_request_node_id: str
    to_source_id: str
    kind: str                                # mentions | constrains
    rule_id: str
    strength: str
    justification: dict[str, Any]


@dataclass
class EvidenceGraph:
    schema_version: str
    version: str
    request_digest: str
    sources: list[SourceRef]
    nodes: list[EvidenceNode]
    edges: list[EvidenceEdge]
    source_edges: list[SourceEdge]
    uncovered_request_nodes: list[str]
    warnings: list[SourceWarning]
    resource_stats: dict[str, Any]
    notes: list[str]
    graph_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw: Any) -> str:
        kw.setdefault("ensure_ascii", False)
        kw.setdefault("sort_keys", True)
        return json.dumps(self.to_dict(), **kw)

    def edges_from(self, request_node_id: str) -> list[EvidenceEdge]:
        return [e for e in self.edges if e.from_request_node_id == request_node_id]

    def source_edges_from(self, request_node_id: str) -> list[SourceEdge]:
        return [e for e in self.source_edges if e.from_request_node_id == request_node_id]

    def node(self, node_id: str) -> EvidenceNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)


# ------------------------------------------------------------------------------------------------------------- schema ---
_SPAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["source_id", "char_start", "char_end", "text", "digest", "byte_start", "byte_end", "line_start", "line_end", "row", "column"],
    "properties": {
        "source_id": {"type": "string", "pattern": "^s-[0-9a-f]{16}$"},
        "char_start": {"type": "integer", "minimum": 0}, "char_end": {"type": "integer", "minimum": 0},
        "text": {"type": "string"}, "digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "byte_start": {"type": ["integer", "null"]}, "byte_end": {"type": ["integer", "null"]},
        "line_start": {"type": ["integer", "null"]}, "line_end": {"type": ["integer", "null"]},
        "row": {"type": ["integer", "null"]}, "column": {"type": ["integer", "null"]},
    },
}
JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://forgesdlc.com/schemas/forge.models.evidence_graph.v0.1.json",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "version", "request_digest", "sources", "nodes", "edges", "source_edges", "uncovered_request_nodes",
                 "warnings", "resource_stats", "notes", "graph_digest"],
    "properties": {
        "schema_version": {"const": EVIDENCE_SCHEMA_VERSION},
        "version": {"type": "string"},
        "request_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
        "sources": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source_id", "attachment_digest", "normalized_safe_path", "origin", "media_type", "encoding", "size_bytes", "decoded"],
            "properties": {
                "source_id": {"type": "string", "pattern": "^s-[0-9a-f]{16}$"},
                "attachment_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
                "normalized_safe_path": {"type": "string", "minLength": 1},
                "origin": {"enum": ["upload", "paste", "tool_output"]},
                "media_type": {"enum": ["text", "markdown", "json", "yaml", "csv", "env", "zip", "binary", "unknown"]},
                "encoding": {"enum": ["utf-8", "utf-8-sig", "latin-1", None]},
                "size_bytes": {"type": "integer", "minimum": 0}, "decoded": {"type": "boolean"}}}},
        "nodes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "span", "lexical_type", "provenance", "parsed_key", "parsed_value"],
            "properties": {
                "id": {"type": "string", "pattern": "^e-[0-9a-f]{16}$"}, "span": _SPAN_SCHEMA,
                "lexical_type": {"enum": list(LEXICAL_TYPES)}, "provenance": {"type": "string"},
                "parsed_key": {"type": ["string", "null"]}, "parsed_value": {"type": ["string", "null"]}}}},
        "edges": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "from_request_node_id", "to_evidence_node_id", "kind", "rule_id", "strength", "justification"],
            "properties": {
                "id": {"type": "string", "pattern": "^x-[0-9a-f]{16}$"},
                "from_request_node_id": {"type": "string", "pattern": "^[ocquk p]\\d+$"},
                "to_evidence_node_id": {"type": "string", "pattern": "^e-[0-9a-f]{16}$"},
                "kind": {"enum": list(EDGE_KINDS)}, "rule_id": {"type": "string", "pattern": "^g2\\."},
                "strength": {"enum": list(STRENGTHS)}, "justification": {"type": "object"}}}},
        "source_edges": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "from_request_node_id", "to_source_id", "kind", "rule_id", "strength", "justification"],
            "properties": {
                "id": {"type": "string", "pattern": "^y-[0-9a-f]{16}$"},
                "from_request_node_id": {"type": "string", "pattern": "^[ocquk]\\d+$|^p\\d+$"},
                "to_source_id": {"type": "string", "pattern": "^s-[0-9a-f]{16}$"},
                "kind": {"enum": ["mentions", "constrains"]}, "rule_id": {"type": "string", "pattern": "^g2\\."},
                "strength": {"enum": list(STRENGTHS)}, "justification": {"type": "object"}}}},
        "uncovered_request_nodes": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["code", "attachment", "detail"],
            "properties": {"code": {"type": "string"}, "attachment": {"type": "string"}, "detail": {"type": "string"}}}},
        "resource_stats": {"type": "object"},
        "notes": {"type": "array", "items": {"type": "string"}},
        "graph_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    },
    # no decision / policy / allow field exists in this schema — additionalProperties: False enforces it
}
JSON_SCHEMA["properties"]["edges"]["items"]["properties"]["from_request_node_id"]["pattern"] = "^[ocquk]\\d+$|^p\\d+$"
_VALIDATOR = Draft202012Validator(JSON_SCHEMA)
_FORBIDDEN_KEYS = ("decision", "policy", "allow", "allowed", "authorized", "execute", "permission")


def validate_evidence_graph(doc: dict[str, Any], sources_text: Optional[dict[str, str]] = None) -> list[str]:
    """Schema + invariant check. Returns a list of problems (empty = valid).

    ``sources_text`` (source_id → decoded text) enables the span round-trip and digest check.
    """
    problems = [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in sorted(_VALIDATOR.iter_errors(doc), key=str)]
    node_ids = {n["id"] for n in doc.get("nodes", [])}
    src_ids = {s["source_id"] for s in doc.get("sources", [])}
    for n in doc.get("nodes", []):
        sp = n["span"]
        if sp["source_id"] not in src_ids:
            problems.append(f"node {n['id']}: unknown source {sp['source_id']}")
        if sp["char_end"] <= sp["char_start"]:
            problems.append(f"node {n['id']}: empty span")
        if sp["digest"] != "sha256:" + sha256_hex(sp["text"].encode("utf-8", "surrogatepass")):
            problems.append(f"node {n['id']}: span digest mismatch")
        if sources_text is not None and sp["source_id"] in sources_text:
            if sources_text[sp["source_id"]][sp["char_start"]:sp["char_end"]] != sp["text"]:
                problems.append(f"node {n['id']}: span text does not round-trip")
    for e in doc.get("source_edges", []):
        if e["to_source_id"] not in src_ids:
            problems.append(f"source edge {e['id']}: unknown source")
        for k in _FORBIDDEN_KEYS:
            if k in e["justification"]:
                problems.append(f"source edge {e['id']}: forbidden justification key {k}")
    for e in doc.get("edges", []):
        if e["to_evidence_node_id"] not in node_ids:
            problems.append(f"edge {e['id']}: unknown evidence node")
        if e["kind"] in ("supports", "contradicts") and e["strength"] != "typed_comparison":
            problems.append(f"edge {e['id']}: {e['kind']} without typed_comparison")
        if e["kind"] in ("supports", "contradicts") and not (e["justification"].get("request_side") and e["justification"].get("evidence_side")):
            problems.append(f"edge {e['id']}: {e['kind']} without both-side spans")
        for k in _FORBIDDEN_KEYS:
            if k in e["justification"]:
                problems.append(f"edge {e['id']}: forbidden justification key {k}")
    for k in _FORBIDDEN_KEYS:
        if k in doc:
            problems.append(f"forbidden top-level key {k}")
    body = {k: v for k, v in doc.items() if k != "graph_digest"}
    if doc.get("graph_digest") != _digest_of(body):
        problems.append("graph_digest mismatch")
    return problems


def _digest_of(body: dict[str, Any]) -> str:
    return "sha256:" + sha256_hex(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8", "surrogatepass"))


# ------------------------------------------------------------------------------------------------------ anchor terms ---
@dataclass(frozen=True)
class _Anchor:
    node_id: str
    text: str                 # literal to find
    kind: str                 # path | identifier | literal | number | name
    role: str                 # "object" (constraint target_object/value) | "text"
    local_start: int          # offset inside the node text (for justification)


_PATH_RE = re.compile(r"(?<![\w./!-])[\w.\-]+\.(?:zip|jar|whl)![\w.\-]+(?:/[\w.\-]+)*"                   # archive!member as one term
                      r"|(?<![\w./-])(?:[\w.\-]+/)+[\w.\-]*|(?<![\w./-])[\w\-]+(?:\.[\w\-]+)*\.(?=[A-Za-z][A-Za-z0-9]{0,7}\b)[A-Za-z][A-Za-z0-9]{0,7}\b")
_IDENT_RE = re.compile(r"(?<![\w.])(?:[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+|[a-z]+(?:[A-Z][a-z0-9]+)+|[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|[A-Z]{2,}[0-9]*|[a-z0-9]+(?:-[a-z0-9]+)+)(?![\w.])")
_LITERAL_RE = re.compile(r"\"([^\"\n]{1,120})\"|'([^'\n]{1,120})'|`([^`\n]{1,120})`")
_NUMBER_RE = re.compile(r"(?<![\w.\-])(?:\d+\.\d+|\d{2,})(?:\s?(?:ms|s|m|h|d|%|kb|mb|gb|kib|mib|gib))?(?![\w.])", re.I)
_NAME_RE = re.compile(r"(?<![\w.])(?!(?:[A-Z][a-z]+)$)([A-Z][a-z]{2,}[A-Za-z0-9]*)(?![\w.])")
_STOP_NAMES = {"The", "This", "That", "These", "Those", "Please", "Then", "After", "Before", "When", "Unless", "Until", "Only",
               "Also", "And", "But", "Not", "Never", "Always", "Should", "Would", "Could", "Make", "Open", "Run", "Create",
               "Write", "Draft", "List", "Show", "Explain", "Compare", "Summarize", "Summarise", "Check", "Read", "Keep", "Save",
               "Imagine", "Suppose", "What", "Which", "Where", "Who", "How", "Why", "Otherwise", "Deliverables", "Deliverable",
               "Two", "Three", "Four", "Five", "One", "First", "Second", "Third", "English", "French", "German", "Ukrainian"}
_STOP_IDENTS = {"e.g", "i.e", "etc", "vs", "read-only", "on-call", "sign-off", "go-ahead", "thumbs-up", "all-clear", "third-party",
                "re-run", "non-english", "customer-facing", "internal-only", "one-paragraph", "step-by-step", "high-level"}
_ASSERTION_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_.\-]*)(?:\s+(?:value|setting|field|key|count|number|limit|option|parameter|flag|column))?\s*(?:==|=|:|\bis set to\b|\bset to\b|\bequals\b|\bshould be\b|\bmust be\b|\bis\b|\bare\b|\bof\b)\s*"
    r"(?P<val>\"[^\"\n]{1,80}\"|'[^'\n]{1,80}'|`[^`\n]{1,80}`|-?\d+(?:\.\d+)?(?:\s?(?:ms|s|m|h|d|%))?|true|false|yes|no|on|off|enabled|disabled|[A-Za-z][\w.\-/]{0,60})(?![\w.])",
    re.I)
_ASSERTION_STOP_KEYS = {"it", "this", "that", "there", "here", "what", "which", "who", "when", "if", "and", "or", "the", "a", "an",
                        "value", "values", "number", "one", "two", "three", "for", "in", "on", "to", "of", "with", "as", "is", "are"}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]*")
# pronoun / vague objects that make a clause a candidate-inheriting one (conventions § 5 `unresolved_with_candidates`)
_VAGUE_OBJECT_RE = re.compile(
    r"\b(?:it|them|those|these|(?:that|this)(?:\s+one)?|(?:the|that|this|those|these)\s+(?:issue|problem|setting|file|value|entry|record|"
    r"section|line|item|result|change|error|bug|field|key|row|cell|config|configuration|option|parameter|flag|member|note|ticket|task|page|"
    r"document|table|list|ones?|values|entries|records|items|lines|rows|errors|settings|files))\s*[.!?,;:]*\s*$", re.I)
# request words that must not be treated as attachment keys even when a key of that name exists (generic English, not a selector)
_STOP_WORDS = {"this", "that", "these", "those", "with", "from", "into", "onto", "about", "after", "before", "then", "than", "when",
               "what", "which", "where", "while", "there", "their", "they", "them", "have", "will", "would", "should", "could", "must",
               "please", "make", "sure", "also", "only", "just", "like", "same", "each", "every", "some", "both", "file", "files",
               "value", "values", "field", "fields", "list", "item", "items", "text", "line", "lines", "info", "note", "notes", "kind",
               "table", "column", "columns", "cell", "cells", "key", "keys", "section", "document", "attached", "attachment", "attachments",
               "tell", "show", "read", "check", "find", "look", "give", "send", "write", "draft", "open", "update", "change", "edit",
               "delete", "remove", "create", "summarize", "summarise", "explain", "compare", "describe", "says", "said", "does", "done",
               "contents", "content", "whether", "because", "without", "within", "against", "using", "based", "need", "needs", "want"}


def _node_texts(ir: S.RequestIR) -> list[tuple[str, str, int, list[tuple[str, int, str]]]]:
    """[(node_id, text, span_start, objects)] where objects = [(text, local_start, role)] for constraint targets."""
    out = []
    g = ir.graph
    for o in g.objectives:
        out.append((o.id, o.text, o.source_span.start, []))
    for c in g.constraints:
        objs: list[tuple[str, int, str]] = []
        for m in (c.target_object, c.value):
            if m is not None and m.text:
                objs.append((m.text, max(0, m.source_span.start - c.source_span.start), "object"))
        out.append((c.id, c.text, c.source_span.start, objs))
    for q in g.conditions:
        out.append((q.id, q.text, q.source_span.start, []))
    for u in g.unresolved:
        out.append((u.id, u.text, u.source_span.start, []))
    for k in g.context_statements:
        out.append((k.id, k.text, k.source_span.start, []))
    return out


_TOKEN_REGION_KINDS = ("path", "inline_code", "url")            # verbatim tokens: safe to use as literal anchors, never interpreted
_CONTENT_REGION_KINDS = ("code_fence", "quotation", "json_like", "yaml_like", "command_like", "attachment")   # opaque content


_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u2018", "\u2019"), ("«", "»"))


def _region_payload(kind: str, core: str) -> str:
    """The verbatim payload of an opaque region: quotation marks and fence delimiters are not part of what must recur in a source."""
    if kind == "quotation":
        for a, b in _QUOTE_PAIRS:
            if len(core) >= 2 and core.startswith(a) and core.endswith(b):
                return core[1:-1].strip()
        return core
    if kind == "code_fence":
        lines = core.splitlines()
        if lines and lines[0].lstrip().startswith(("```", "~~~")):
            lines = lines[1:]
        if lines and lines[-1].strip() in ("```", "~~~"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return core


def _inside_protected(ir: S.RequestIR, abs_start: int, abs_end: int) -> bool:
    """True when the span lies inside an *opaque* protected region (content kinds); token kinds stay anchorable."""
    for p in ir.graph.protected_regions:
        if p.kind in _CONTENT_REGION_KINDS and abs_start >= p.source_span.start and abs_end <= p.source_span.end:
            return True
    return False


def _anchors_for(ir: S.RequestIR) -> list[_Anchor]:
    anchors: list[_Anchor] = []
    seen: set[tuple[str, str]] = set()

    def add(nid: str, text: str, kind: str, role: str, local: int, abs_start: int) -> None:
        t = text.strip()
        if len(t) < 2 or (nid, t.lower()) in seen:
            return
        if _inside_protected(ir, abs_start, abs_start + len(t)) and kind != "literal":
            return
        seen.add((nid, t.lower()))
        anchors.append(_Anchor(nid, t, kind, role, local))

    for nid, text, start, objs in _node_texts(ir):
        for otext, olocal, _ in objs:
            # the object of a constraint anchors as a whole phrase only when it is a path/identifier/literal; otherwise its terms do
            for m in _PATH_RE.finditer(otext):
                add(nid, m.group(0), "path", "object", olocal + m.start(), start + olocal + m.start())
            for m in _IDENT_RE.finditer(otext):
                if m.group(0).lower() not in _STOP_IDENTS:
                    add(nid, m.group(0), "identifier", "object", olocal + m.start(), start + olocal + m.start())
            for m in _LITERAL_RE.finditer(otext):
                add(nid, next(g for g in m.groups() if g is not None), "literal", "object", olocal + m.start() + 1, start + olocal + m.start() + 1)
            for m in _NAME_RE.finditer(otext):
                if m.group(1) not in _STOP_NAMES:
                    add(nid, m.group(1), "name", "object", olocal + m.start(1), start + olocal + m.start(1))
        member_spans: list[tuple[int, int]] = []
        for m in _PATH_RE.finditer(text):
            add(nid, m.group(0), "path", "text", m.start(), start + m.start())
            if "!" in m.group(0):
                member_spans.append((m.start(), m.end()))
        for m in _LITERAL_RE.finditer(text):
            add(nid, next(g for g in m.groups() if g is not None), "literal", "text", m.start() + 1, start + m.start() + 1)
        for m in _IDENT_RE.finditer(text):
            if any(a <= m.start() and m.end() <= b for a, b in member_spans):
                continue                                                   # "bundle.zip" inside "bundle.zip!docs/plan.md" is not a separate term
            if m.group(0).lower() not in _STOP_IDENTS:
                add(nid, m.group(0), "identifier", "text", m.start(), start + m.start())
        for m in _NUMBER_RE.finditer(text):
            add(nid, m.group(0), "number", "text", m.start(), start + m.start())
        for m in _NAME_RE.finditer(text):
            if m.group(1) not in _STOP_NAMES and m.start(1) > 0:          # a capital at the clause start is sentence case, not a name
                add(nid, m.group(1), "name", "text", m.start(1), start + m.start(1))
    return anchors


@dataclass(frozen=True)
class _Assertion:
    node_id: str
    key: str
    value: str
    local_start: int
    local_end: int


def _normalize_scalar(v: str) -> tuple[str, Any]:
    t = v.strip().strip("`\"'").strip()
    low = t.lower()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", low):
        return "number", float(low)
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s?(ms|s|m|h|d|%)", low)
    if m:
        return f"number:{m.group(2)}", float(m.group(1))
    if low in ("true", "yes", "on", "enabled"):
        return "bool", True
    if low in ("false", "no", "off", "disabled"):
        return "bool", False
    return "string", low


def _assertions_for(ir: S.RequestIR) -> list[_Assertion]:
    """Candidate ``key <op> value`` assertions in request nodes (filtered against attachment keys by the caller)."""
    out: list[_Assertion] = []
    for nid, text, start, _ in _node_texts(ir):
        for m in _ASSERTION_RE.finditer(text):
            key = m.group("key")
            if key.lower() in _ASSERTION_STOP_KEYS or len(key) < 2:
                continue
            if _inside_protected(ir, start + m.start(), start + m.end()):
                continue
            out.append(_Assertion(nid, key, m.group("val"), m.start(), m.end()))
    return out


# ------------------------------------------------------------------------------------------- clause source scope (G2H) ---
# A typed comparison binds only to the source(s) the asserting clause names unambiguously. Protocol: artifacts/DCE-G2H/01_PROTOCOL.md.
_SCOPE_EXTS = {"yaml", "yml", "json", "ini", "env", "csv", "tsv", "md", "txt", "toml", "cfg", "conf", "xml", "properties", "zip",
               "jar", "whl", "py", "js", "ts", "html", "htm", "log", "sql", "sh", "rst", "pdf", "docx", "xlsx"}
# a clause that explicitly sets two named sources side by side
_COMPARE_CUE_RE = re.compile(r"\b(?:compar(?:e|es|ed|ing|ison)|versus|vs\.?|against|agree|agrees|match|matches|matching|consistent|"
                             r"same|differ|differs|difference|differences|diff|in\s+sync|line\s+up|equal|equivalent|identical|reconcile|"
                             r"between)\b", re.I)
_SCOPE_BINDING_REGION_KINDS = ("path",)      # a bare path token binds; quotation / inline code / fences / urls bind nothing (brief rule 6)


@dataclass(frozen=True)
class _Scope:
    kind: str                                # single | pair | ambiguous | unattached | global
    named: tuple[str, ...]                   # file terms the clause (or its pair clause) names, request order
    sources: tuple[str, ...]                 # source ids in scope (empty for ambiguous / unattached)
    via_node_id: Optional[str] = None        # pair scope inherited from a neighbouring clause

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "named": list(self.named), "sources": list(self.sources)}
        if self.via_node_id:
            d["via_node_id"] = self.via_node_id
        return d


_GLOBAL_SCOPE = _Scope("global", (), ())


def _file_like(term: str) -> bool:
    if "/" in term or "!" in term:
        return True
    return term.rsplit(".", 1)[-1].lower() in _SCOPE_EXTS if "." in term else False


def _scope_terms(ir: S.RequestIR, nid: str, text: str, start: int) -> list[str]:
    """Path tokens of one clause that may bind a source: plain text or a G1 ``path`` region; nothing inside quotes / code / urls."""
    out: list[str] = []
    for m in _PATH_RE.finditer(text):
        a, b = start + m.start(), start + m.end()
        blocked = any(p.kind not in _SCOPE_BINDING_REGION_KINDS and a >= p.source_span.start and b <= p.source_span.end
                      for p in ir.graph.protected_regions)
        term = m.group(0).strip().lstrip("./")
        if blocked or not _file_like(term) or term in out:
            continue
        out.append(term)
    return out


def _sources_named_by(term: str, sources: list[SourceRef]) -> list[str]:
    """Source ids a file term may denote: exact normalised path / ZIP member, basename, or their case-insensitive forms."""
    t = term.lower()
    hits: list[str] = []
    for s in sources:
        path = s.normalized_safe_path
        member = path.split("!")[-1]
        pl, ml = path.lower(), member.lower()
        if (path == term or member == term or member.endswith("/" + term) or member.rsplit("/", 1)[-1] == term or
                pl == t or ml == t or ml.endswith("/" + t) or ml.rsplit("/", 1)[-1] == t):
            hits.append(s.source_id)
    return hits


def _bind_terms(terms: list[str], sources: list[SourceRef]) -> tuple[list[str], list[str], list[str]]:
    """(bound source ids in term order, ambiguous terms, unattached terms). A term that matches several sources is bound only when the
    other terms of the same clause take every competing source exactly (``app.yaml`` beside ``configs/app.yaml``)."""
    cands = {t: _sources_named_by(t, sources) for t in terms}
    exact: dict[str, str] = {}
    for t, hs in cands.items():
        ex = [s.source_id for s in sources if s.source_id in hs and (s.normalized_safe_path == t or s.normalized_safe_path.lower() == t.lower())]
        if len(ex) == 1:
            exact[t] = ex[0]
    bound: list[str] = []
    ambiguous: list[str] = []
    unattached: list[str] = []
    for t in terms:
        hs = cands[t]
        if not hs:
            unattached.append(t)
            continue
        if len(hs) == 1:
            sid = hs[0]
        elif t in exact and all(sid in exact.values() for sid in hs):
            sid = exact[t]                                                   # every competitor is taken exactly by a sibling term
        else:
            taken = {v for k, v in exact.items() if k != t}
            rest = [sid for sid in hs if sid not in taken]
            if len(rest) != 1:
                ambiguous.append(t)
                continue
            sid = rest[0]
        if sid not in bound:
            bound.append(sid)
    return bound, ambiguous, unattached


def _clause_scopes(ir: S.RequestIR, sources: list[SourceRef]) -> dict[str, _Scope]:
    """Scope of every request clause (protected regions excluded). Pair scope flows from a neighbouring clause (±1 in request order)
    only when that clause names two or more attached sources unambiguously and carries a comparison cue."""
    ordered = sorted(((nid, text, start) for nid, text, start, _ in _node_texts(ir)), key=lambda t: t[2])
    own: dict[str, tuple[list[str], list[str], list[str], list[str], bool]] = {}
    for nid, text, start in ordered:
        terms = _scope_terms(ir, nid, text, start)
        bound, amb, una = _bind_terms(terms, sources)
        own[nid] = (terms, bound, amb, una, bool(_COMPARE_CUE_RE.search(text)))
    def neighbour_pair(idx: int) -> Optional[tuple[str, list[str], list[str]]]:
        for j in (idx - 1, idx + 1):
            if 0 <= j < len(ordered):
                onid = ordered[j][0]
                oterms, obound, _oa, _ou, ocue = own[onid]
                if ocue and len(obound) >= 2:
                    return onid, oterms, obound
        return None

    scopes: dict[str, _Scope] = {}
    for idx, (nid, _text, _start) in enumerate(ordered):
        terms, bound, amb, una, _cue = own[nid]
        if bound:
            pair = neighbour_pair(idx) if len(bound) == 1 else None
            if pair is not None and bound[0] in pair[2]:                  # the named file is one member of the explicit pair next door
                scopes[nid] = _Scope("pair", tuple(pair[1]), tuple(pair[2]), via_node_id=pair[0])
            else:
                scopes[nid] = _Scope("pair" if len(bound) >= 2 else "single", tuple(terms), tuple(bound))
            continue
        if amb:
            scopes[nid] = _Scope("ambiguous", tuple(terms), ())
            continue
        if una:
            scopes[nid] = _Scope("unattached", tuple(terms), ())
            continue
        pair = neighbour_pair(idx)
        scopes[nid] = _Scope("pair", tuple(pair[1]), tuple(pair[2]), via_node_id=pair[0]) if pair is not None else _GLOBAL_SCOPE
    return scopes


def _request_words(ir: S.RequestIR) -> list[tuple[str, str, int, str]]:
    """(node id, word, local offset, lower-cased word) for plain words that may name an attachment key (conventions § 2 rule 9)."""
    out: list[tuple[str, str, int, str]] = []
    for nid, text, start, _ in _node_texts(ir):
        if nid.startswith("p"):
            continue
        for m in _WORD_RE.finditer(text):
            w = m.group(0)
            wl = w.lower()
            if len(wl) < 4 or wl in _STOP_WORDS or _inside_protected(ir, start + m.start(), start + m.end()):
                continue
            out.append((nid, w, m.start(), wl))
    return out


_KEY_NORM_TBL = str.maketrans({" ": "_", "\t": "_", "\n": "_", "\r": "_", "\f": "_", "\v": "_", "-": "_"})
_IDX_SUFFIX_RE = re.compile(r"\[\d+\]$")


def _key_norm(k: str) -> str:
    if k.islower() and "-" not in k and " " not in k and "\t" not in k:
        return k.strip()
    return k.strip().lower().translate(_KEY_NORM_TBL)


def _key_matches(request_key: str, fact_key: str) -> bool:
    """Reference semantics (conventions § 2 rule 3); ``_KeyIndex`` is the indexed equivalent used by the builder."""
    return _key_norm(request_key) in _key_forms(fact_key)


def _key_forms(fact_key: str) -> set[str]:
    """All normalised request keys that ``_key_matches`` accepts for this fact key (full path, last segment, dotted suffixes)."""
    fk = _key_norm(fact_key)
    parts = fk.split(".")
    forms = {fk}
    last = parts[-1]
    if last.endswith("]"):
        last = _IDX_SUFFIX_RE.sub("", last)
    forms.add(last)
    for i in range(1, len(parts)):
        forms.add(".".join(parts[i:]))
    return forms


class _KeyIndex:
    """Per-source index with the semantics of ``_key_matches``: a request key matches a fact whose normalised key equals it, whose
    last segment (index stripped) equals it, or which ends with ``"." + key``. Full keys and last segments are hashed; dotted
    request keys (rare) use a linear suffix scan. Results are in document order."""

    def __init__(self, src: DecodedSource, request_keys: set[str]) -> None:
        """``request_keys`` are the normalised keys the request can ask about; only facts matching one of them are indexed."""
        self.by_key: dict[str, list[Fact]] = {}
        dotted = [("." + rk, rk) for rk in request_keys if "." in rk]
        for f in src.facts:
            if not f.key:
                continue
            fk = _key_norm(f.key)
            if fk in request_keys:
                self.by_key.setdefault(fk, []).append(f)
                hit_full = fk
            else:
                hit_full = None
            if "." in fk:
                last = fk.rsplit(".", 1)[-1]
                if last.endswith("]"):
                    last = _IDX_SUFFIX_RE.sub("", last)
                if last != hit_full and last in request_keys:
                    self.by_key.setdefault(last, []).append(f)
                for suffix, rk in dotted:
                    if rk != hit_full and rk != last and fk.endswith(suffix):
                        self.by_key.setdefault(rk, []).append(f)
            elif fk.endswith("]"):
                last = _IDX_SUFFIX_RE.sub("", fk)
                if last != hit_full and last in request_keys:
                    self.by_key.setdefault(last, []).append(f)

    def lookup(self, request_key: str) -> list[Fact]:
        return self.by_key.get(_key_norm(request_key), [])


# ----------------------------------------------------------------------------------------------------------- building ---
def _span(src: DecodedSource, a: int, b: int, row: Optional[int] = None, column: Optional[int] = None) -> EvidenceSpan:
    text = src.text[a:b]
    bs, be = byte_offsets(src.text, src.ref.encoding or "utf-8", a, b)
    return EvidenceSpan(src.ref.source_id, a, b, text, "sha256:" + sha256_hex(text.encode("utf-8", "surrogatepass")),
                        bs, be, line_of(src.line_starts, a), line_of(src.line_starts, max(a, b - 1)), row, column)


def _node_id(source_id: str, a: int, b: int) -> str:
    return "e-" + sha256_hex(f"{source_id}|{a}|{b}".encode("utf-8"))[:16]


def _edge_id(frm: str, to: str, kind: str, rule: str) -> str:
    return "x-" + sha256_hex(f"{frm}|{to}|{kind}|{rule}".encode("utf-8"))[:16]


def _find_all(hay: str, needle: str, *, word: bool, cap: int) -> tuple[list[int], str]:
    """Occurrences of needle in hay: exact first; if none, case-insensitive. Returns (positions, strength)."""
    def scan(h: str, n: str) -> list[int]:
        out: list[int] = []
        i = h.find(n)
        while i >= 0 and len(out) < cap:
            if not word or ((i == 0 or not (h[i - 1].isalnum() or h[i - 1] == "_")) and
                            (i + len(n) >= len(h) or not (h[i + len(n)].isalnum() or h[i + len(n)] == "_"))):
                out.append(i)
            i = h.find(n, i + 1)
        return out
    pos = scan(hay, needle)
    if pos:
        return pos, "exact"
    pos = scan(hay.lower(), needle.lower())
    return pos, "lexical"


class _FactLocator:
    """Fact whose value span (or key span) contains [a, b). When facts are in document order (always true for the built-in
    scanners) a bisect on char_start plus the neighbouring facts is definitive — a key span precedes its own value span, so the
    *next* fact may own a position inside its key. Unsorted lists fall back to the linear rule."""

    def __init__(self, src: DecodedSource) -> None:
        self.facts = src.facts
        self.starts = [f.char_start for f in self.facts]
        self.sorted = all(self.starts[i] <= self.starts[i + 1] for i in range(len(self.starts) - 1))

    def at(self, a: int, b: int) -> Optional[Fact]:
        facts = self.facts
        if not facts:
            return None
        if self.sorted:
            i = bisect.bisect_right(self.starts, a) - 1
            for j in (i, i + 1, i - 1):
                if 0 <= j < len(facts):
                    f = facts[j]
                    if f.char_start <= a and b <= f.char_end:
                        return f
                    if f.key_start is not None and f.key_start <= a and b <= (f.key_end or -1):
                        return f
            return None
        for f in facts:
            if f.char_start <= a and b <= f.char_end:
                return f
            if f.key_start is not None and f.key_start <= a and b <= (f.key_end or -1):
                return f
        return None


def build_evidence_graph(ir: S.RequestIR, attachments: list[AttachmentInput], *, limits: ResourceLimits = ResourceLimits(),
                         utterance: Optional[str] = None) -> EvidenceGraph:
    if not isinstance(ir, S.RequestIR):
        raise TypeError("ir must be a RequestIR")
    if not isinstance(attachments, list) or not all(isinstance(a, AttachmentInput) for a in attachments):
        raise TypeError("attachments must be a list[AttachmentInput]")
    if not isinstance(limits, ResourceLimits):
        raise TypeError("limits must be a ResourceLimits")
    ss = load_sources(attachments, limits)
    warnings = list(ss.warnings)
    stats: dict[str, Any] = dict(ss.stats)
    stats["limits"] = limits.as_dict()
    stats["anchors"] = 0
    stats["assertions"] = 0
    stats["matches_capped"] = 0
    nodes: dict[str, EvidenceNode] = {}
    edges: dict[str, EvidenceEdge] = {}
    decoded = [s for s in ss.sources if s.ref.decoded and s.text]
    cap = 25

    locators = {src.ref.source_id: _FactLocator(src) for src in decoded}
    scopes = _clause_scopes(ir, [s.ref for s in ss.sources])                 # G2H: which source(s) each clause talks about

    def scope_rule(nid: str, src: DecodedSource) -> Optional[str]:
        """None when ``src`` is in the clause's scope; otherwise the mentions rule that says why a typed edge is not emitted."""
        sc = scopes.get(nid, _GLOBAL_SCOPE)
        if sc.kind == "global" or src.ref.source_id in sc.sources:
            return None
        return {"ambiguous": "g2.mentions.scope_ambiguous_source", "unattached": "g2.mentions.scope_unattached_source"}.get(
            sc.kind, "g2.mentions.out_of_scope_key_match")

    def in_scope_first(nid: str) -> list[DecodedSource]:
        sc = scopes.get(nid, _GLOBAL_SCOPE)
        return sorted(decoded, key=lambda s: 0 if (sc.kind == "global" or s.ref.source_id in sc.sources) else 1)

    def ensure_node(src: DecodedSource, a: int, b: int, ltype: str, prov: str) -> EvidenceNode:
        nid = _node_id(src.ref.source_id, a, b)
        if nid in nodes:
            return nodes[nid]
        f = locators[src.ref.source_id].at(a, b)
        if f is not None and f.char_start == a and f.char_end == b:
            ltype, key, val = f.kind, f.key, f.value
        elif f is not None:
            key, val = f.key, f.value
        else:
            key = val = None
        n = EvidenceNode(nid, _span(src, a, b, f.row if f else None, f.column if f else None), ltype, prov, key, val)
        nodes[nid] = n
        return n

    def add_edge(frm: str, node: EvidenceNode, kind: str, rule: str, strength: str, just: dict[str, Any]) -> None:
        eid = _edge_id(frm, node.id, kind, rule)
        if eid not in edges:
            edges[eid] = EvidenceEdge(eid, frm, node.id, kind, rule, strength, just)

    # constraint metadata for constrains edges
    cmeta = {c.id: c for c in ir.graph.constraints}

    # 1. lexical anchors → mentions / constrains
    anchors = _anchors_for(ir)
    stats["anchors"] = len(anchors)
    for anc in anchors:
        word = anc.kind in ("identifier", "number", "name") or (anc.kind == "literal" and " " not in anc.text)
        for src in decoded:
            pos, strength = _find_all(src.text, anc.text, word=word, cap=cap)
            if len(pos) >= cap:
                stats["matches_capped"] += 1
            for p in pos:
                node = ensure_node(src, p, p + len(anc.text), anc.kind, f"match:{anc.kind}")
                c = cmeta.get(anc.node_id)
                if c is not None and anc.role == "object" and c.kind in ("prohibition", "exclusion"):
                    add_edge(anc.node_id, node, "constrains", f"g2.constrains.{c.kind}_object", strength,
                             {"constraint_kind": c.kind, "constraint_scope": c.scope, "breadth": c.breadth,
                              "applies_to_objective_ids": list(c.applies_to_objective_ids), "target_action": c.target_action,
                              "object": anc.text, "request_local_offset": anc.local_start,
                              "note": "links the constraint's named object to its occurrences; does not widen or assert the prohibition"})
                else:
                    add_edge(anc.node_id, node, "mentions", f"g2.mentions.{anc.kind}", strength,
                             {"term": anc.text, "request_local_offset": anc.local_start, "anchor_role": anc.role})

    # 1b. path / filename anchors naming a whole source (basename or full normalised path)
    sedges: dict[str, SourceEdge] = {}
    for anc in anchors:
        if anc.kind not in ("path", "literal", "identifier"):
            continue
        term = anc.text.strip().lstrip("./")
        if not term or "/" not in term and "." not in term:
            continue
        for src in ss.sources:
            path = src.ref.normalized_safe_path
            member = path.split("!")[-1]
            hit = None
            if path == term or member == term:
                hit = "exact_path"
            elif member.endswith("/" + term) or member.rsplit("/", 1)[-1] == term:
                hit = "basename"
            elif path.lower() == term.lower() or member.lower().rsplit("/", 1)[-1] == term.lower():
                hit = "basename_ci"
            if hit is None:
                continue
            c = cmeta.get(anc.node_id)
            kind = "constrains" if (c is not None and anc.role == "object" and c.kind in ("prohibition", "exclusion")) else "mentions"
            rule = f"g2.source.{kind}.{hit}"
            sid = "y-" + sha256_hex(f"{anc.node_id}|{src.ref.source_id}|{kind}".encode("utf-8"))[:16]   # one edge per node×source×kind
            if sid in sedges:
                continue
            just: dict[str, Any] = {"term": anc.text, "matched_path": path, "match": hit, "request_local_offset": anc.local_start}
            if kind == "constrains":
                just.update({"constraint_kind": c.kind, "constraint_scope": c.scope, "breadth": c.breadth,
                             "applies_to_objective_ids": list(c.applies_to_objective_ids), "target_action": c.target_action,
                             "note": "names the constrained file; does not widen or assert the prohibition"})
            sedges[sid] = SourceEdge(sid, anc.node_id, src.ref.source_id, kind, rule, "exact" if hit != "basename_ci" else "lexical", just)

    # 1c. request words that name a structured key in an attachment ("the deadline" ↔ `Deadline: Friday`) → mentions (key span)
    words = _request_words(ir)
    candidates = _assertions_for(ir)
    request_keys = {wl for _, _, _, wl in words} | {_key_norm(a.key) for a in candidates}
    key_index = {src.ref.source_id: _KeyIndex(src, request_keys) for src in decoded}
    seen_keys: set[tuple[str, str]] = set()
    for nid, w, local, wl in words:
        if (nid, wl) in seen_keys:
            continue
        for src in in_scope_first(nid):
            for f in key_index[src.ref.source_id].lookup(wl):
                if f.kind == "key_value" and f.key_start is not None and f.key_end is not None:
                    ks, ke = f.key_start, f.key_end
                elif f.kind == "heading" and f.column is not None:          # CSV / Markdown table header cell
                    ks, ke = f.char_start, f.char_end
                else:
                    continue
                if ke <= ks:
                    continue
                seen_keys.add((nid, wl))
                node = ensure_node(src, ks, ke, "fact_key", "match:fact_key")
                srule = scope_rule(nid, src)
                just = {"term": w, "fact_key": f.key, "request_local_offset": local, "anchor_role": "text"}
                if srule is not None:
                    just["scope"] = scopes[nid].as_dict()
                add_edge(nid, node, "mentions", srule or "g2.mentions.fact_key", "exact" if src.text[ks:ke] == w else "lexical", just)
                break

    # 2. typed comparisons → supports / contradicts (only assertions whose key exists in some attachment, and only against the
    #    source(s) the asserting clause names — G2H; every other key match is a mentions edge whose rule names the scope reason)
    assertions = [a for a in candidates if any(key_index[s.ref.source_id].lookup(a.key) for s in decoded)]
    stats["assertions"] = len(assertions)
    stats["clause_scopes"] = {k: sum(1 for sc in scopes.values() if sc.kind == k) for k in ("single", "pair", "ambiguous", "unattached", "global")}
    for asr in assertions:
        rtype, rval = _normalize_scalar(asr.value)
        scope = scopes.get(asr.node_id, _GLOBAL_SCOPE)
        for src in decoded:
            for f in key_index[src.ref.source_id].lookup(asr.key):
                if f.kind not in ("key_value", "cell") or f.value is None:
                    continue
                srule = scope_rule(asr.node_id, src)
                if srule is not None:
                    node = ensure_node(src, f.char_start, f.char_end, f.kind, f"scan:{src.ref.media_type}")
                    add_edge(asr.node_id, node, "mentions", srule, "lexical",
                             {"request_key": asr.key, "request_value": asr.value, "fact_key": f.key, "fact_value": f.value,
                              "scope": scope.as_dict(), "note": "key match outside the clause's source scope; no typed comparison"})
                    continue
                ftype, fval = _normalize_scalar(f.value)
                comparable = (rtype == ftype) or (rtype.startswith("number") and ftype.startswith("number") and
                                                  (rtype == "number" or ftype == "number"))
                if not comparable:
                    node = ensure_node(src, f.char_start, f.char_end, f.kind, f"scan:{src.ref.media_type}")
                    add_edge(asr.node_id, node, "mentions", "g2.mentions.key_match_incomparable_values", "lexical",
                             {"request_key": asr.key, "request_value": asr.value, "fact_key": f.key, "fact_value": f.value})
                    continue
                equal = (rval == fval) if not isinstance(rval, float) else abs(rval - fval) < 1e-9
                node = ensure_node(src, f.char_start, f.char_end, f.kind, f"scan:{src.ref.media_type}")
                kind = "supports" if equal else "contradicts"
                just = {
                    "request_side": {"node_id": asr.node_id, "local_start": asr.local_start, "local_end": asr.local_end,
                                     "key": asr.key, "value": asr.value, "normalized": [rtype, rval]},
                    "evidence_side": {"source_id": src.ref.source_id, "key": f.key, "value": f.value,
                                      "key_span": [f.key_start, f.key_end], "value_span": [f.char_start, f.char_end],
                                      "line": f.line, "row": f.row, "column": f.column, "normalized": [ftype, fval]},
                    "comparison": "equal" if equal else "different",
                    "scope": scope.as_dict(),
                    "note": "typed key/value comparison of two literal spans; not entailment about the request as a whole",
                }
                add_edge(asr.node_id, node, kind, f"g2.typed.key_value_{'equal' if equal else 'differs'}", "typed_comparison", just)

    # 3. protected regions → verbatim digest match only
    if ir.graph.protected_regions:
        if utterance is None or S.utterance_digest(utterance) != ir.digest:
            warnings.append(SourceWarning("protected_regions_unlinked", "<request>",
                                          "utterance not supplied (or digest mismatch); protected regions were not matched"))
        else:
            for p in ir.graph.protected_regions:
                region = utterance[p.source_span.start:p.source_span.end]
                core = region.strip()
                if p.kind in _TOKEN_REGION_KINDS:
                    tok = core.strip("`").strip()
                    for src in ss.sources:
                        path = src.ref.normalized_safe_path
                        member = path.split("!")[-1]
                        if tok and (path == tok or member == tok or member.rsplit("/", 1)[-1] == tok.lstrip("./")):
                            rule = "g2.source.mentions.protected_path"
                            sid = "y-" + sha256_hex(f"{p.id}|{src.ref.source_id}|mentions".encode("utf-8"))[:16]
                            sedges.setdefault(sid, SourceEdge(sid, p.id, src.ref.source_id, "mentions", rule, "exact",
                                                              {"protected_kind": p.kind, "token": tok, "matched_path": path}))
                    continue
                core = _region_payload(p.kind, core)
                if len(core) < 4:
                    continue
                for src in decoded:
                    pos, strength = _find_all(src.text, core, word=False, cap=cap)
                    if strength != "exact":
                        continue
                    for q in pos:
                        node = ensure_node(src, q, q + len(core), "verbatim", "match:protected_region")
                        add_edge(p.id, node, "mentions", "g2.protected.verbatim_in_source", "exact",
                                 {"protected_kind": p.kind, "region_digest": "sha256:" + sha256_hex(core.encode("utf-8", "surrogatepass")),
                                  "note": "digest-equal verbatim occurrence; the region content was not interpreted"})

    # 3b. candidate antecedents (G2 burned repair): a pronoun / vague clause with no evidence of its own ("apply it", "fix that one",
    #     "handle the issue") inherits the evidence of the nearest preceding clause as *candidates*. No referent is asserted.
    ordered = sorted(((nid, text, start) for nid, text, start, _ in _node_texts(ir) if not nid.startswith("p")), key=lambda t: t[2])
    for idx, (nid, text, start) in enumerate(ordered):
        if nid.startswith("k") or not _VAGUE_OBJECT_RE.search(text):
            continue
        if any(e.from_request_node_id == nid for e in edges.values()) or any(e.from_request_node_id == nid for e in sedges.values()):
            continue
        for anid, _, _ in reversed(ordered[:idx]):
            a_edges = [e for e in edges.values() if e.from_request_node_id == anid and e.rule_id != "g2.mentions.candidate_antecedent"]
            a_sedges = [e for e in sedges.values() if e.from_request_node_id == anid and e.rule_id != "g2.source.mentions.candidate_antecedent"]
            if not a_edges and not a_sedges:
                continue
            just_note = "candidate evidence inherited from the preceding clause; no referent is asserted (resolution is out of scope)"
            for e in a_edges:
                add_edge(nid, nodes[e.to_evidence_node_id], "mentions", "g2.mentions.candidate_antecedent", "lexical",
                         {"antecedent_node_id": anid, "via_rule": e.rule_id, "via_kind": e.kind, "note": just_note})
            for e in a_sedges:
                sid = "y-" + sha256_hex(f"{nid}|{e.to_source_id}|mentions".encode("utf-8"))[:16]
                sedges.setdefault(sid, SourceEdge(sid, nid, e.to_source_id, "mentions", "g2.source.mentions.candidate_antecedent", "lexical",
                                                  {"antecedent_node_id": anid, "via_rule": e.rule_id, "via_kind": e.kind, "note": just_note}))
            break

    # 4. uncovered request nodes (objectives, constraints, conditions, unresolved; context statements and protected regions too)
    all_ids = ([o.id for o in ir.graph.objectives] + [c.id for c in ir.graph.constraints] + [q.id for q in ir.graph.conditions] +
               [u.id for u in ir.graph.unresolved] + [k.id for k in ir.graph.context_statements] + [p.id for p in ir.graph.protected_regions])
    covered = {e.from_request_node_id for e in edges.values()} | {e.from_request_node_id for e in sedges.values()}
    uncovered = [i for i in all_ids if i not in covered]

    node_list = sorted(nodes.values(), key=lambda n: (n.span.source_id, n.span.char_start, n.span.char_end))
    src_order = {s.ref.source_id: i for i, s in enumerate(ss.sources)}
    node_list.sort(key=lambda n: (src_order.get(n.span.source_id, 1 << 30), n.span.char_start, n.span.char_end))
    edge_list = sorted(edges.values(), key=lambda e: (_req_order(e.from_request_node_id), e.to_evidence_node_id, e.kind, e.rule_id))
    sedge_list = sorted(sedges.values(), key=lambda e: (_req_order(e.from_request_node_id), src_order.get(e.to_source_id, 1 << 30), e.kind, e.rule_id))
    stats["nodes"] = len(node_list)
    stats["edges"] = len(edge_list)
    stats["source_edges"] = len(sedge_list)
    stats["edges_by_kind"] = {k: sum(1 for e in edge_list if e.kind == k) + sum(1 for e in sedge_list if e.kind == k) for k in EDGE_KINDS}
    g = EvidenceGraph(EVIDENCE_SCHEMA_VERSION, EVIDENCE_GRAPH_VERSION, ir.digest, [s.ref for s in ss.sources], node_list, edge_list,
                      sedge_list, uncovered, warnings, stats, list(NOTES))
    body = g.to_dict()
    body.pop("graph_digest", None)
    g.graph_digest = _digest_of(body)
    return g


def _req_order(nid: str) -> tuple[int, int]:
    pref = nid[0]
    try:
        return (REQUEST_NODE_PREFIXES.index(pref), int(nid[1:]))
    except (ValueError, IndexError):
        return (99, 0)


def sources_text_map(attachments: list[AttachmentInput], limits: ResourceLimits = ResourceLimits()) -> dict[str, str]:
    """source_id → decoded text, for validate_evidence_graph's round-trip check (re-decodes deterministically)."""
    return {s.ref.source_id: s.text for s in load_sources(attachments, limits).sources}
