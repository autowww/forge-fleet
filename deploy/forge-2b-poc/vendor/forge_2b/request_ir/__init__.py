"""DCE-G1/G1R — deterministic RequestIR / IntentGraph parser.

The chat lane reads it to classify a turn. It does not authorize or execute anything.

Public API: ``parse_request(utterance, context=None, *, strict=False) -> RequestIR`` (``strict`` adds JSON-Schema validation);
``ReadOnlyContext`` (referent names only); ``RequestIR`` with ``to_dict(redact_text=…)``, ``to_json``, ``summary``,
``validate(utterance)``; ``SCHEMA``; read-only ``policy_view`` helpers (never authorize or execute anything);
DCE-G1R3A additive ``effect_view``: ``project_effects(ir) -> EffectProjection`` (reply_only / artifact_write / environment_mutation /
command_execution / unknown, with evidence spans) and ``effect_policy(ir, effect) -> DENY | REQUIRE_RESOLUTION | TEXT_NOT_PROHIBITED``
(never ALLOW; a parser cannot grant authorization).
No LLM, no network, no filesystem, no shared mutable state. Independent of ``forge_2b.dce`` (DCE-01) and DCS PlanIR.
"""
from .effect_view import PROJECTION_VERSION, EffectProjection, effect_policy, project_effects
from .parser import parse_request
from .schema import (ACTION_CLASS, ACTIONS, CONDITION_KINDS, CONSTRAINT_KINDS, LINK_KINDS, MAX_CLAUSES, MAX_UTTERANCE_CHARS,
                     PARSER_VERSION, SCHEMA, SCHEMA_VERSION, STATUSES, UNRESOLVED_KINDS, Condition, Constraint, IntentGraph, Objective,
                     ReadOnlyContext, RequestIR, utterance_digest)

__all__ = ["parse_request", "RequestIR", "IntentGraph", "Objective", "Constraint", "Condition", "ReadOnlyContext", "SCHEMA", "SCHEMA_VERSION",
           "PARSER_VERSION", "ACTIONS", "ACTION_CLASS", "CONSTRAINT_KINDS", "CONDITION_KINDS", "LINK_KINDS", "UNRESOLVED_KINDS", "STATUSES",
           "MAX_UTTERANCE_CHARS", "MAX_CLAUSES", "utterance_digest", "project_effects", "effect_policy", "EffectProjection", "PROJECTION_VERSION"]
