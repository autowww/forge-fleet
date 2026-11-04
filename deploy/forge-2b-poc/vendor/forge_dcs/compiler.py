"""Deterministic STRICT compiler: normalized request + pinned rule pack -> PlanIR v0.1.

No I/O other than reading the bundled rule pack. No model calls. No clock. No randomness.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from forge_dcs import __version__, errors
from forge_dcs.canonical import NORMALIZATION_VERSION, digest, normalize_prompt, plan_hash, prompt_tokens
from forge_dcs.contracts import CompileRequest, FileRef
from forge_dcs.graph_validation import raise_if_invalid, topological_order
from forge_dcs.schema_registry import PLANIR_ID, assert_valid

SCHEMA_VERSION = "planir.v0.1"
TOKENIZER_UNVERIFIED = "TOKEN_BUDGET_UNVERIFIED"
RULEPACK_FILE = "rulepack.v0.1.json"

SCHEMA_EXTRACT_INPUT = "urn:forge-dcs:schema:extract_input:v0"
SCHEMA_EXTRACTED_FACTS = "urn:forge-dcs:schema:extracted_facts:v0"
SCHEMA_COMPARE_INPUT = "urn:forge-dcs:schema:compare_input:v0"
SCHEMA_COMPARISON = "urn:forge-dcs:schema:comparison_result:v0"
SCHEMA_VALIDATION_REPORT = "urn:forge-dcs:schema:validation_report:v0"
VALIDATOR_SCHEMA_SOURCE = "dcs.validators.schema_and_source_refs.v0"
VALIDATOR_COMPARE = "dcs.validators.comparison_reconciliation.v0"


@lru_cache(maxsize=1)
def load_rulepack() -> tuple[dict[str, Any], str]:
    raw = resources.files("forge_dcs").joinpath("rules").joinpath(RULEPACK_FILE).read_text(encoding="utf-8")
    data = json.loads(raw)
    return data, digest(data)


# --- node builders -------------------------------------------------------------------------


def _scope(f: FileRef) -> str:
    return f"{f.file_id}@{f.content_hash}"


def _fragment(f: FileRef) -> str:
    # Templates bind the whole document (#root). Sub-document fragment *selection* is P04
    # retrieval; P02 only guarantees that #pNNNN refs can be validated against the registry.
    return f"{f.file_id}@{f.version}#root"


def _model_node(
    *,
    node_id: str,
    operation: str,
    routing_class: str,
    sources: list[FileRef],
    depends_on: list[str],
    bindings: list[dict[str, Any]],
    task_class: str,
    input_modality: str,
    input_schema_ref: str,
    output_schema_ref: str,
    ctx_tokens: int,
    max_output_tokens: int,
    rp: dict[str, Any],
    preferred: dict[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "node_id": node_id,
        "operation": operation,
        "routing_class": routing_class,
        "depends_on": sorted(depends_on),
        "source_scope": sorted(_scope(s) for s in sources),
        "fragment_refs": sorted(_fragment(s) for s in sources),
        "input_bindings": sorted(bindings, key=lambda b: b["bind_as"]),
        "input_schema_ref": input_schema_ref,
        "output_schema_ref": output_schema_ref,
        "required_capabilities": {
            "task_class": task_class,
            "input_modality": input_modality,
            "output_format": "json_schema",
            "min_context_tokens": ctx_tokens,
            "max_output_tokens": max_output_tokens,
            "languages": list(rp["defaults"]["languages"]),
            "tools_required": False,
        },
        "model_policy": dict(rp["defaults"]["model_policy"]),
        "token_budget": {"max_input_tokens": ctx_tokens, "max_output_tokens": max_output_tokens},
        "verification_policy": {
            "validators": ["json_schema", "source_ref_required"],
            "source_ref_required": True,
            "stop_conditions": ["OUTPUT_SCHEMA_INVALID", "UNAUTHORIZED_SOURCE"],
        },
    }
    if preferred:
        node["preferred_capabilities"] = preferred
    return node


def _zero_model_node(
    *, node_id: str, depends_on: list[str], bindings: list[dict[str, Any]], validator_ref: str, output_schema_ref: str
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "operation": "validate",
        "routing_class": "zero_model",
        "depends_on": sorted(depends_on),
        "source_scope": [],
        "fragment_refs": [],
        "input_bindings": sorted(bindings, key=lambda b: b["bind_as"]),
        "output_schema_ref": output_schema_ref,
        "verification_policy": {
            "validators": ["json_schema", "source_ref_required", "no_fabricated_values"],
            "validator_ref": validator_ref,
            "source_ref_required": True,
            "stop_conditions": ["OUTPUT_SCHEMA_INVALID"],
        },
    }


def _binding(from_node: str, path: str, alias: str, schema_ref: str) -> dict[str, Any]:
    return {"from_node": from_node, "output_path": path, "bind_as": alias, "schema_ref": schema_ref}


def _edges_from(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Exactly one edge per (dependency, binding alias); one control edge per unbound dependency.

    Multiple distinct bindings from the same predecessor yield multiple edges, each carrying its
    own ``binding_ref`` — none is dropped. Order: ``(from, to, binding_ref)``; for plans with one
    binding per predecessor this is byte-identical to the P01 ordering ``(from, to)``.
    """
    edges: list[dict[str, Any]] = []
    for t in tasks:
        by_dep: dict[str, list[str]] = {}
        for b in t["input_bindings"]:
            by_dep.setdefault(b["from_node"], []).append(b["bind_as"])
        for d in t["depends_on"]:
            aliases = by_dep.get(d)
            if aliases:
                for alias in sorted(aliases):
                    edges.append({"from": d, "to": t["node_id"], "binding_ref": alias})
            else:
                edges.append({"from": d, "to": t["node_id"]})
    return sorted(edges, key=lambda e: (e["from"], e["to"], e.get("binding_ref", "")))


# --- templates -----------------------------------------------------------------------------


def _tpl_extract_single_source(req: CompileRequest, rp: dict[str, Any]) -> list[dict[str, Any]]:
    src = req.file_refs[0]
    rc = rp["routing_class_by_operation"]
    extract = _model_node(
        node_id="extract_main",
        operation="extract",
        routing_class=rc["extract"],
        sources=[src],
        depends_on=[],
        bindings=[],
        task_class="structured_extraction",
        input_modality="text",
        input_schema_ref=SCHEMA_EXTRACT_INPUT,
        output_schema_ref=SCHEMA_EXTRACTED_FACTS,
        ctx_tokens=req.max_context_tokens_per_task,
        max_output_tokens=rp["defaults"]["extract_max_output_tokens"],
        rp=rp,
    )
    validate = _zero_model_node(
        node_id="validate_main",
        depends_on=["extract_main"],
        bindings=[_binding("extract_main", "$.facts", "extracted_facts", SCHEMA_EXTRACTED_FACTS)],
        validator_ref=VALIDATOR_SCHEMA_SOURCE,
        output_schema_ref=SCHEMA_VALIDATION_REPORT,
    )
    return [extract, validate]


def _tpl_compare_two_sources(req: CompileRequest, rp: dict[str, Any]) -> list[dict[str, Any]]:
    a, b = req.file_refs[0], req.file_refs[1]
    rc = rp["routing_class_by_operation"]
    ctx = req.max_context_tokens_per_task
    common = dict(
        operation="extract",
        routing_class=rc["extract"],
        depends_on=[],
        bindings=[],
        task_class="structured_extraction",
        input_modality="text",
        input_schema_ref=SCHEMA_EXTRACT_INPUT,
        output_schema_ref=SCHEMA_EXTRACTED_FACTS,
        ctx_tokens=ctx,
        max_output_tokens=rp["defaults"]["extract_max_output_tokens"],
        rp=rp,
    )
    extract_a = _model_node(node_id="extract_a", sources=[a], **common)
    extract_b = _model_node(node_id="extract_b", sources=[b], **common)
    compare = _model_node(
        node_id="compare_ab",
        operation="compare",
        routing_class=rc["compare"],
        sources=[],
        depends_on=["extract_a", "extract_b"],
        bindings=[
            _binding("extract_a", "$.facts", "source_a_facts", SCHEMA_EXTRACTED_FACTS),
            _binding("extract_b", "$.facts", "source_b_facts", SCHEMA_EXTRACTED_FACTS),
        ],
        task_class="comparison",
        input_modality="json",
        input_schema_ref=SCHEMA_COMPARE_INPUT,
        output_schema_ref=SCHEMA_COMPARISON,
        ctx_tokens=min(2 * ctx, 32768),
        max_output_tokens=rp["defaults"]["compare_max_output_tokens"],
        rp=rp,
        preferred={"reasoning_tier": "strong", "prefer_resident_model": False},
    )
    verify = _zero_model_node(
        node_id="verify_compare",
        depends_on=["compare_ab"],
        bindings=[_binding("compare_ab", "$.comparison", "comparison_result", SCHEMA_COMPARISON)],
        validator_ref=VALIDATOR_COMPARE,
        output_schema_ref=SCHEMA_VALIDATION_REPORT,
    )
    return [extract_a, extract_b, compare, verify]


_TEMPLATES = {
    "extract_single_source": _tpl_extract_single_source,
    "compare_two_sources": _tpl_compare_two_sources,
}


# --- rule matching -------------------------------------------------------------------------


def _match_rule(req: CompileRequest, rp: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    norm = normalize_prompt(req.prompt)
    tokens = set(prompt_tokens(norm))
    unresolved: list[dict[str, Any]] = []
    for rule in rp["rules"]:
        m = rule["match"]
        if not any(tok in tokens for tok in m["any_tokens"]):
            continue
        if len(req.file_refs) != m["file_count"]:
            unresolved.append(
                {
                    "code": errors.SOURCE_COUNT_MISMATCH,
                    "message": f"rule {rule['rule_id']} requires exactly {m['file_count']} file_refs; got {len(req.file_refs)}",
                }
            )
            return None, unresolved
        for required in m.get("requires", []):
            if not getattr(req, required, None):
                unresolved.append(
                    {
                        "code": errors.COMPARISON_DIMENSION_MISSING if required == "comparison_dimension" else "REQUIRED_FIELD_MISSING",
                        "message": f"rule {rule['rule_id']} requires request field {required!r}",
                    }
                )
                return None, unresolved
        return rule, unresolved
    unresolved.append({"code": errors.UNSUPPORTED_INTENT, "message": "no pinned rule matches the normalized prompt"})
    return None, unresolved


# --- compile -------------------------------------------------------------------------------


def compile_plan(req: CompileRequest, tenant_id: str, registry: Any | None = None) -> dict[str, Any]:
    """``registry`` (a ``forge_dcs.store.SourceStore``) is optional. Without one the compile is
    exactly the P01 behaviour. With one, every ``file_refs`` entry must be registered for this
    tenant with the claimed ``content_hash`` and the persisted bytes must re-hash to it
    (``SOURCE_VERSION_UNKNOWN``, 422) — the caller's hash never becomes authority on its own.
    The emitted plan bytes are identical either way."""
    rp, rp_digest = load_rulepack()
    fragment_index = None
    if registry is not None and req.file_refs:
        problems = registry.resolve(tenant_id, req.file_refs)
        if problems:
            raise errors.DcsError(errors.SOURCE_VERSION_UNKNOWN, "file_refs are not registered sources", http_status=422, details=problems)
        fragment_index = registry.fragment_index(tenant_id, req.file_refs)
    rule, unresolved = _match_rule(req, rp)
    norm = normalize_prompt(req.prompt)

    tasks: list[dict[str, Any]] = []
    if rule is not None:
        tasks = _TEMPLATES[rule["template"]](req, rp)
        order = topological_order([t["node_id"] for t in tasks], {t["node_id"]: t["depends_on"] for t in tasks})
        if order is None:  # pragma: no cover - templates are acyclic by construction
            raise errors.DcsError(errors.CYCLE_DETECTED, "template produced a cycle", http_status=500)
        by_id = {t["node_id"]: t for t in tasks}
        tasks = [by_id[n] for n in order]

    model_nodes = [t for t in tasks if t["routing_class"] != "zero_model"]
    plan: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "compiler_version": __version__,
        "rule_pack_version": rp["rule_pack_version"],
        "rule_pack_digest": rp_digest,
        "normalization_version": NORMALIZATION_VERSION,
        "tenant_id": tenant_id,
        "determinism_class": "STRICT",
        "tokenizer_profile": TOKENIZER_UNVERIFIED,
        "intent": {
            "normalized_prompt_digest": digest(norm),
            "rule_id": rule["rule_id"] if rule else None,
            "operation": rule["operation"] if rule else None,
            "requested_fields": sorted(req.requested_fields),
            "comparison_dimension": req.comparison_dimension,
        },
        "source_versions": sorted(
            ({"file_id": f.file_id, "version": f.version, "content_hash": f.content_hash} for f in req.file_refs),
            key=lambda s: (s["file_id"], s["version"]),
        ),
        "tasks": tasks,
        "edges": _edges_from(tasks),
        "coverage": {
            "status": "COMPLETE" if rule else "UNSUPPORTED_INTENT",
            "sources_covered": len(req.file_refs) if rule else 0,
            # NOTE: this string is part of the hashed plan; it is frozen for planir.v0.1 hash
            # compatibility (P01 golden vectors) and will be revised with PlanIR v0.2.
            "notes": ["fragment_refs are whole-document placeholders until P02 ingestion"] if rule else [],
        },
        "unresolved": unresolved,
        "estimated_cost": {
            "model_nodes": len(model_nodes),
            "zero_model_nodes": len(tasks) - len(model_nodes),
            "max_input_tokens_total": sum(t["token_budget"]["max_input_tokens"] for t in model_nodes),
        },
    }
    # Semantic invariants are enforced before any hash exists (§4.4 "reject ... before hashing");
    # the schema check runs after, because planir.v0.1 requires plan_hash to be present.
    raise_if_invalid(plan, fragment_index)
    plan["plan_hash"] = plan_hash(plan)
    assert_valid(PLANIR_ID, plan)
    return plan
