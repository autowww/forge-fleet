"""DCE-G3 — selective small-model graph resolution (read-only, advisory, experimental).

Public surface::

    from forge_2b.resolution import resolve, Budget, NullBackend, RecordedBackend, OpenAICompatibleBackend, OpenAICompatibleConfig
    result = resolve(ir, utterance, graph, backend=NullBackend(), sources_text=sources_text_map(attachments))
    result.overlay.to_json(); validate_overlay(result.overlay.to_dict())

Guarantees: RequestIR v0.1 and EvidenceGraph v0.1 are never mutated; the overlay (``forge.models.resolution.v0.2``) carries
no authorization vocabulary; every accepted reading is advisory and names what was verified (``binding``); free-text
interpretations are recorded apart as UNVERIFIED; coverage candidates are UNVERIFIED; zero model calls on non-English,
rejected or fully covered requests; ``max_total_calls`` caps actual backend attempts (retries included) and an assembled
prompt over ``max_input_tokens`` is never sent; ``backend=None`` performs selection only. Nothing here reads the
environment or opens a socket at import time.
"""
from .backends import (BackendError, BackendResult, NullBackend, OpenAICompatibleBackend, OpenAICompatibleConfig, RecordedBackend, Recording,
                       RecordingMiss, prompt_digest)
from .contracts import (BINDINGS, COVERAGE_STATUS, DISPOSITIONS, FORBIDDEN_KEYS, PROPOSAL_SCHEMA_VERSION, REQUEST_SCHEMA_VERSION,
                        RESOLUTION_SCHEMA_VERSION, RESOLVER_VERSION, UNVERIFIED_STATUS, VERIFIED_RELATIONS, VERIFIER_VERSION, Budget, OVERLAY_SCHEMA,
                        PROPOSAL_SCHEMA, REQUEST_SCHEMA, ResolutionOverlay, ResolutionProposal, ResolutionRequest, VerifierFinding, validate_overlay,
                        validate_proposal, validate_request)
from .prompts import PROMPT_VERSION
from .resolver import ResolveResult, TraceEntry, ir_digest, resolve
from .selection import Selection, coverage_gaps, select
from .verifier import BUDGET_RULES, Scope, TypedAudit, audit_typed_edges, clause_scope, comparison_binds, unanchored_literals, verify

__all__ = [
    "resolve", "ResolveResult", "TraceEntry", "ir_digest", "Budget", "select", "Selection", "coverage_gaps", "verify", "audit_typed_edges", "TypedAudit",
    "Scope", "clause_scope", "comparison_binds", "unanchored_literals", "BUDGET_RULES",
    "NullBackend", "RecordedBackend", "Recording", "RecordingMiss", "OpenAICompatibleBackend", "OpenAICompatibleConfig", "BackendError", "BackendResult",
    "prompt_digest", "PROMPT_VERSION", "RESOLUTION_SCHEMA_VERSION", "REQUEST_SCHEMA_VERSION", "PROPOSAL_SCHEMA_VERSION", "RESOLVER_VERSION",
    "VERIFIER_VERSION", "COVERAGE_STATUS", "UNVERIFIED_STATUS", "DISPOSITIONS", "VERIFIED_RELATIONS", "BINDINGS", "FORBIDDEN_KEYS", "OVERLAY_SCHEMA",
    "PROPOSAL_SCHEMA", "REQUEST_SCHEMA", "ResolutionOverlay", "ResolutionProposal", "ResolutionRequest", "VerifierFinding", "validate_overlay",
    "validate_proposal", "validate_request",
]
