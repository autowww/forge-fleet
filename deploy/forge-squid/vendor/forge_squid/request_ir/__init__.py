"""DCE-G1/G1R — deterministic RequestIR / IntentGraph parser.

The chat lane reads it to classify a turn. It does not authorize or execute anything.

Public API: ``parse_request(utterance, context=None, *, strict=False) -> RequestIR`` (``strict`` adds JSON-Schema validation);
``ReadOnlyContext`` (referent names only); ``RequestIR`` with ``to_dict(redact_text=…)``, ``to_json``, ``summary``,
``validate(utterance)``; ``SCHEMA``; read-only ``policy_view`` helpers (never authorize or execute anything);
DCE-G1R3A additive ``effect_view``: ``project_effects(ir) -> EffectProjection`` (reply_only / artifact_write / environment_mutation /
command_execution / unknown, with evidence spans) and ``effect_policy(ir, effect) -> DENY | REQUIRE_RESOLUTION | TEXT_NOT_PROHIBITED``
(never ALLOW; a parser cannot grant authorization).
DCE-G1R3B additive ``operation_view``: ``project_operations(ir, tool_declarations=None) -> OperationProjection`` (per objective a
``primary_operation`` plus the **set** of ``potential_effects`` from an auditable operator registry, ``unknown_external_effects``,
evidence) and ``operation_policy(ir, node_id)`` — denies an operation when **any** potential effect is prohibited.
DCE-G1R3E additive ``integrity``: ``integrity_findings(ir, utterance)`` / ``integrity_report`` / ``integrity_ok`` — the graph-integrity
invariant (conventions v6 rule 34): directive text that produced neither an objective nor an unresolved node is reported, never
silently dropped; any ``error`` finding means REQUIRE_RESOLUTION for consumers.
DCE-G2 additive ``evidence_graph`` (schema ``forge.models.evidence_graph.v0.1``): ``build_evidence_graph(ir, attachments) ->
EvidenceGraph`` links RequestIR node ids to candidate evidence spans in caller-supplied attachments (``AttachmentInput``; text, bytes,
or ZIP) with ``mentions`` / ``constrains`` / typed ``supports`` / ``contradicts`` edges, exact provenance and resource warnings. It reads
attachments; it never promotes their content to instructions, never edits the RequestIR, and carries no decision field.
No LLM, no network, no filesystem, no shared mutable state. Independent of ``forge_squid.dce`` (DCE-01) and DCS PlanIR.
"""
from .effect_view import PROJECTION_VERSION, EffectProjection, effect_policy, project_effects
from .evidence_graph import (EVIDENCE_GRAPH_VERSION, EVIDENCE_SCHEMA_VERSION, EvidenceEdge, EvidenceGraph, EvidenceNode, EvidenceSpan,
                             SourceEdge, build_evidence_graph, validate_evidence_graph)
from .evidence_sources import AttachmentInput, ResourceLimits, SourceRef, SourceWarning, load_sources
from .integrity import INTEGRITY_VERSION, IntegrityFinding, IntegrityReport, integrity_findings, integrity_ok, integrity_report
from .operation_view import (OPERATION_PROJECTION_VERSION, OPERATOR_REGISTRY, OperationEffect, OperationProjection, ToolDeclaration,
                             operation_policy, project_operations)
from .parser import parse_request
from .schema import (ACTION_CLASS, ACTIONS, CONDITION_KINDS, CONSTRAINT_KINDS, DEFAULT_LANGUAGE_SCOPE, LANGUAGE_SCOPES, LINK_KINDS, MAX_CLAUSES, MAX_UTTERANCE_CHARS,
                     PARSER_VERSION, SCHEMA, SCHEMA_VERSION, STATUSES, UNRESOLVED_KINDS, Condition, Constraint, IntentGraph, Objective,
                     ReadOnlyContext, RequestIR, utterance_digest)

__all__ = ["parse_request", "RequestIR", "IntentGraph", "Objective", "Constraint", "Condition", "ReadOnlyContext", "SCHEMA", "SCHEMA_VERSION",
           "PARSER_VERSION", "ACTIONS", "ACTION_CLASS", "CONSTRAINT_KINDS", "CONDITION_KINDS", "LINK_KINDS", "UNRESOLVED_KINDS", "STATUSES",
           "MAX_UTTERANCE_CHARS", "MAX_CLAUSES", "utterance_digest", "project_effects", "effect_policy", "EffectProjection", "PROJECTION_VERSION",
           "project_operations", "operation_policy", "OperationProjection", "OperationEffect", "ToolDeclaration", "OPERATOR_REGISTRY",
           "OPERATION_PROJECTION_VERSION", "LANGUAGE_SCOPES", "DEFAULT_LANGUAGE_SCOPE",
           "integrity_findings", "integrity_report", "integrity_ok", "IntegrityFinding", "IntegrityReport", "INTEGRITY_VERSION",
           "build_evidence_graph", "validate_evidence_graph", "EvidenceGraph", "EvidenceNode", "EvidenceEdge", "EvidenceSpan", "SourceEdge",
           "EVIDENCE_GRAPH_VERSION", "EVIDENCE_SCHEMA_VERSION", "AttachmentInput", "ResourceLimits", "SourceRef", "SourceWarning", "load_sources"]
