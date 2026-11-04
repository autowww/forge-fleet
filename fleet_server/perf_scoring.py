"""Deterministic performance intelligence scoring (modeled independent-node capacity)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

SCORING_VERSION = "1.0"
SCORE_TYPE = "modeled_independent_node_capacity"

DEFAULT_WEIGHTS: dict[str, float] = {
    "postgresql": 22.0,
    "duckdb": 28.0,
    "sqlite": 10.0,
    "numpy": 12.0,
    "nlp": 28.0,
}

STAGE_LABELS: dict[str, str] = {
    "postgresql": "PostgreSQL",
    "duckdb": "DuckDB",
    "sqlite": "SQLite",
    "numpy": "NumPy",
    "nlp": "NLP 1 GiB",
}

STAGE_UNITS: dict[str, str] = {
    "postgresql": "bundles/s",
    "duckdb": "bundles/s",
    "sqlite": "bundles/s",
    "numpy": "rows/s",
    "nlp": "docs/s",
}

STAGE_ORDER = ("postgresql", "duckdb", "sqlite", "numpy", "nlp")


@dataclass
class StageRates:
    single: float
    max_rate: float
    max_workers: int | None = None


@dataclass
class NodeEvidence:
    node_id: str
    label: str
    evidence: str
    stages: dict[str, StageRates] = field(default_factory=dict)
    connectivity: str | None = None
    profile: str | None = None
    fixture_id: str | None = None
    physical_cores: int | None = None
    logical_cpus: int | None = None
    hardware_score: float | None = None
    run_id: str | None = None


@dataclass
class ScoringPolicy:
    baseline_node_id: str
    weights: dict[str, float] | None = None
    include_snapshots: bool = False
    baseline_fixture_id: str | None = None
    baseline_profile: str = "standard"


def normalize_weights(
    raw: Mapping[str, float],
    *,
    expected_keys: frozenset[str] | None = None,
) -> dict[str, float]:
    keys = expected_keys or frozenset(DEFAULT_WEIGHTS)
    if set(raw.keys()) != set(keys):
        raise ValueError("Unexpected workload weight keys")
    if any(float(v) < 0 for v in raw.values()) or sum(float(v) for v in raw.values()) <= 0:
        raise ValueError("Weights must be nonnegative and at least one must be positive")
    total = sum(float(v) for v in raw.values())
    return {k: float(raw[k]) / total for k in keys}


def _eligible_for_inclusion(node: NodeEvidence, include_snapshots: bool) -> bool:
    if node.evidence == "recorded":
        return True
    if include_snapshots and node.evidence == "saved_snapshot":
        return True
    return False


def _baseline_rates(node: NodeEvidence, stage_ids: tuple[str, ...]) -> dict[str, float]:
    out: dict[str, float] = {}
    for sid in stage_ids:
        st = node.stages.get(sid)
        if st is None or st.max_rate <= 0:
            raise ValueError(f"Baseline {node.node_id} missing positive max rate: {sid}")
        out[sid] = st.max_rate
    return out


def _stage_index(max_rate: float, baseline_rate: float) -> float:
    return 100.0 * max_rate / baseline_rate


def compute_from_handoff_fixture(
    fixture: dict[str, Any],
    *,
    baseline_node_id: str = "precision",
    include_snapshots: bool = True,
    weight_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Oracle-compatible compute for regression tests (handoff fixture shape)."""
    nodes = {n["id"]: n for n in fixture["nodes"]}
    if baseline_node_id not in nodes:
        raise ValueError("Baseline node not present. Real Granite rates must be recorded separately.")
    baseline = nodes[baseline_node_id]
    workloads = fixture["workloads"]
    weights_raw = {w["id"]: float(w["weight"]) for w in workloads}
    if weight_overrides is not None:
        weights_raw.update({k: float(v) for k, v in weight_overrides.items()})
    weights = normalize_weights(weights_raw, expected_keys=frozenset(weights_raw))
    for w in workloads:
        sid = w["id"]
        if sid not in baseline["rate"] or baseline["rate"][sid]["max"] <= 0:
            raise ValueError(f"Baseline {baseline_node_id} missing positive max rate: {sid}")

    included = [
        n
        for n in fixture["nodes"]
        if n["evidence"] == "recorded" or (include_snapshots and n["evidence"] == "saved_snapshot")
    ]
    node_indexes: dict[str, dict[str, float]] = {}
    node_scores: dict[str, float] = {}
    component_indexes = {s["id"]: 0.0 for s in workloads}
    component_contributions = {s["id"]: 0.0 for s in workloads}
    speedups: dict[str, dict[str, float]] = {}
    worker_efficiencies: dict[str, dict[str, float | None]] = {}

    for n in included:
        indexes: dict[str, float] = {}
        speedups[n["id"]] = {}
        worker_efficiencies[n["id"]] = {}
        for s in workloads:
            sid = s["id"]
            data = n["rate"].get(sid)
            if data is None or data["max"] <= 0 or data["single"] <= 0:
                raise ValueError(f"Incomplete required workload {sid} for included node {n['id']}")
            value = 100.0 * data["max"] / baseline["rate"][sid]["max"]
            indexes[sid] = value
            component_indexes[sid] += value
            speedups[n["id"]][sid] = data["max"] / data["single"]
            mw = data.get("max_workers")
            worker_efficiencies[n["id"]][sid] = (
                speedups[n["id"]][sid] / mw if mw else None
            )
        node_indexes[n["id"]] = indexes
        node_scores[n["id"]] = sum(indexes[sid] * weights[sid] for sid in weights)

    for sid in weights:
        component_contributions[sid] = component_indexes[sid] * weights[sid]
    cluster_score = sum(component_contributions.values())
    assert abs(cluster_score - sum(node_scores.values())) < 1e-8
    return {
        "baseline": baseline_node_id,
        "included_nodes": [n["id"] for n in included],
        "weights": weights,
        "node_component_indexes": node_indexes,
        "node_composites": node_scores,
        "component_indexes": component_indexes,
        "component_contributions": component_contributions,
        "cluster_composite": cluster_score,
        "speedups": speedups,
        "worker_efficiencies": worker_efficiencies,
        "excluded_unmeasured_nodes": [n["id"] for n in fixture["nodes"] if n["evidence"] == "not_run"],
        "included_saved_snapshots": [n["id"] for n in included if n["evidence"] == "saved_snapshot"],
        "modeled_only": True,
    }


def load_handoff_fixture(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "perf_screenshot_fixture.json"
    return json.loads(path.read_text(encoding="utf-8"))


def compute_score(
    nodes: list[NodeEvidence],
    policy: ScoringPolicy,
) -> dict[str, Any]:
    """Full view model for API and UI."""
    by_id = {n.node_id: n for n in nodes}
    baseline_node = by_id.get(policy.baseline_node_id)
    if baseline_node is None:
        return _baseline_missing_response(policy, nodes)

    weights = normalize_weights(policy.weights or dict(DEFAULT_WEIGHTS))
    stage_ids = STAGE_ORDER

    try:
        baseline_max = _baseline_rates(baseline_node, stage_ids)
    except ValueError:
        return _baseline_not_measured_response(policy, baseline_node, nodes)

    baseline_status = "measured"
    if policy.baseline_node_id != "local" and baseline_node.evidence != "recorded":
        baseline_status = "temporary_fallback"

    included_cluster: list[NodeEvidence] = []
    excluded: list[dict[str, Any]] = []

    for node in nodes:
        if not _eligible_for_inclusion(node, policy.include_snapshots):
            reason = _exclusion_reason(node, policy.include_snapshots)
            if node.evidence == "not_run" or node.evidence == "unavailable":
                excluded.append({"node_id": node.node_id, "reason": reason})
            elif node.evidence == "saved_snapshot" and not policy.include_snapshots:
                excluded.append({"node_id": node.node_id, "reason": "saved_snapshot_excluded"})
            continue
        if node.profile and node.profile != policy.baseline_profile:
            excluded.append({"node_id": node.node_id, "reason": "incompatible_profile"})
            continue
        if policy.baseline_fixture_id and node.fixture_id and node.fixture_id != policy.baseline_fixture_id:
            excluded.append({"node_id": node.node_id, "reason": "incompatible_fixture"})
            continue
        if not _node_has_complete_stages(node, stage_ids):
            excluded.append({"node_id": node.node_id, "reason": "partial_or_missing_stages"})
            continue
        included_cluster.append(node)

    component_indexes: dict[str, float] = {sid: 0.0 for sid in stage_ids}
    node_out: list[dict[str, Any]] = []
    speedup_matrix: dict[str, dict[str, float | None]] = {}

    for node in nodes:
        components_out: dict[str, Any] = {}
        node_speedups: dict[str, float | None] = {}
        indexes_for_node: dict[str, float] = {}
        composite: float | None = None
        oversubscribed = False

        for sid in stage_ids:
            st = node.stages.get(sid)
            if st is None or st.max_rate <= 0 or st.single <= 0:
                components_out[sid] = {
                    "index": None,
                    "single_rate": st.single if st else None,
                    "max_rate": st.max_rate if st else None,
                    "max_workers": st.max_workers if st else None,
                    "speedup": None,
                    "worker_efficiency": None,
                    "unit": STAGE_UNITS[sid],
                }
                continue
            idx = _stage_index(st.max_rate, baseline_max[sid])
            indexes_for_node[sid] = idx
            sp = st.max_rate / st.single
            eff = sp / st.max_workers if st.max_workers else None
            if st.max_workers and node.logical_cpus and st.max_workers > node.logical_cpus:
                oversubscribed = True
            components_out[sid] = {
                "index": idx,
                "single_rate": st.single,
                "max_rate": st.max_rate,
                "max_workers": st.max_workers,
                "speedup": sp,
                "worker_efficiency": eff,
                "unit": STAGE_UNITS[sid],
            }
            node_speedups[sid] = sp

        if _node_has_complete_stages(node, stage_ids):
            composite = sum(indexes_for_node[sid] * weights[sid] for sid in stage_ids)

        in_cluster = node in included_cluster
        node_out.append({
            "node_id": node.node_id,
            "label": node.label,
            "composite": composite,
            "evidence": node.evidence,
            "connectivity": node.connectivity,
            "included_in_cluster": in_cluster,
            "exclusion_reason": None if in_cluster else _exclusion_reason(node, policy.include_snapshots),
            "physical_cores": node.physical_cores,
            "logical_cpus": node.logical_cpus,
            "hardware_score": node.hardware_score,
            "worker_oversubscription": oversubscribed,
            "components": components_out,
            "run_id": node.run_id,
        })
        speedup_matrix[node.node_id] = node_speedups

        if in_cluster:
            for sid in stage_ids:
                component_indexes[sid] += indexes_for_node[sid]

    components_api: dict[str, Any] = {}
    contributions: dict[str, float] = {}
    for sid in stage_ids:
        contrib = component_indexes[sid] * weights[sid]
        contributions[sid] = contrib
        components_api[sid] = {
            "cluster_index": component_indexes[sid],
            "weighted_contribution": contrib,
            "weight": weights[sid],
            "label": STAGE_LABELS[sid],
            "unit": STAGE_UNITS[sid],
        }

    composite_confirmed = _sum_included_composites(
        nodes, policy, include_snapshots=False, baseline_max=baseline_max, weights=weights
    )
    composite_with_snapshots = _sum_included_composites(
        nodes, policy, include_snapshots=True, baseline_max=baseline_max, weights=weights
    )
    headline = composite_confirmed if not policy.include_snapshots else composite_with_snapshots

    return {
        "ok": True,
        "scoring_version": SCORING_VERSION,
        "score_type": SCORE_TYPE,
        "profile_id": policy.baseline_profile,
        "baseline": {
            "node_id": policy.baseline_node_id,
            "label": baseline_node.label,
            "status": baseline_status,
            "run_id": baseline_node.run_id,
        },
        "weights": weights,
        "weights_display_percent": {k: round(v * 100, 4) for k, v in weights.items()},
        "include_snapshots": policy.include_snapshots,
        "included_node_ids": [n.node_id for n in included_cluster],
        "node_count_total": len(nodes),
        "node_count_scored": sum(1 for n in node_out if n["composite"] is not None),
        "has_saved_only_included": any(n.evidence == "saved_snapshot" for n in included_cluster),
        "components": components_api,
        "nodes": node_out,
        "cluster": {
            "composite": headline,
            "composite_confirmed": composite_confirmed,
            "composite_with_snapshots": composite_with_snapshots,
            "verified_distributed_efficiency": None,
            "composite_status": "modeled",
            "excluded_nodes": excluded,
        },
        "speedups": speedup_matrix,
        "modeled_only": True,
    }


def _sum_included_composites(
    nodes: list[NodeEvidence],
    policy: ScoringPolicy,
    *,
    include_snapshots: bool,
    baseline_max: dict[str, float],
    weights: dict[str, float],
) -> float | None:
    total = 0.0
    count = 0
    stage_ids = STAGE_ORDER
    for node in nodes:
        if not _eligible_for_inclusion(node, include_snapshots):
            continue
        if node.profile and node.profile != policy.baseline_profile:
            continue
        if policy.baseline_fixture_id and node.fixture_id and node.fixture_id != policy.baseline_fixture_id:
            continue
        if not _node_has_complete_stages(node, stage_ids):
            continue
        composite = sum(
            _stage_index(node.stages[sid].max_rate, baseline_max[sid]) * weights[sid]
            for sid in stage_ids
        )
        total += composite
        count += 1
    return float(total) if count else None


def _node_has_complete_stages(node: NodeEvidence, stage_ids: tuple[str, ...]) -> bool:
    for sid in stage_ids:
        st = node.stages.get(sid)
        if st is None or st.max_rate <= 0 or st.single <= 0:
            return False
    return True


def _exclusion_reason(node: NodeEvidence, include_snapshots: bool) -> str:
    if node.evidence == "not_run":
        return "not_measured"
    if node.evidence == "unavailable":
        return "unavailable"
    if node.evidence == "saved_snapshot" and not include_snapshots:
        return "saved_snapshot_excluded"
    if node.evidence == "incompatible":
        return "incompatible"
    return "excluded"


def _baseline_missing_response(policy: ScoringPolicy, nodes: list[NodeEvidence]) -> dict[str, Any]:
    return {
        "ok": True,
        "scoring_version": SCORING_VERSION,
        "score_type": SCORE_TYPE,
        "baseline": {
            "node_id": policy.baseline_node_id,
            "label": policy.baseline_node_id,
            "status": "not_measured",
            "run_id": None,
        },
        "cluster": {
            "composite": None,
            "composite_confirmed": None,
            "composite_with_snapshots": None,
            "verified_distributed_efficiency": None,
            "composite_status": "baseline_not_measured",
            "excluded_nodes": [],
        },
        "nodes": [{"node_id": n.node_id, "label": n.label, "evidence": n.evidence} for n in nodes],
        "components": {},
    }


def _baseline_not_measured_response(
    policy: ScoringPolicy,
    baseline_node: NodeEvidence,
    nodes: list[NodeEvidence],
) -> dict[str, Any]:
    return {
        "ok": True,
        "scoring_version": SCORING_VERSION,
        "score_type": SCORE_TYPE,
        "baseline": {
            "node_id": policy.baseline_node_id,
            "label": baseline_node.label,
            "status": "not_measured",
            "run_id": baseline_node.run_id,
        },
        "cluster": {
            "composite": None,
            "composite_confirmed": None,
            "composite_with_snapshots": None,
            "verified_distributed_efficiency": None,
            "composite_status": "baseline_not_measured",
            "excluded_nodes": [],
        },
        "nodes": [{"node_id": n.node_id, "label": n.label, "evidence": n.evidence} for n in nodes],
        "components": {},
    }


def handoff_fixture_to_nodes(fixture: dict[str, Any]) -> list[NodeEvidence]:
    """Convert handoff JSON to NodeEvidence list (profile standard, fixture from provenance)."""
    out: list[NodeEvidence] = []
    for n in fixture["nodes"]:
        stages: dict[str, StageRates] = {}
        for sid, data in (n.get("rate") or {}).items():
            stages[sid] = StageRates(
                single=float(data["single"]),
                max_rate=float(data["max"]),
                max_workers=data.get("max_workers"),
            )
        evidence = n.get("evidence") or "not_run"
        if evidence == "not_run":
            ev = "not_run"
        elif evidence == "saved_snapshot":
            ev = "saved_snapshot"
        else:
            ev = "recorded"
        out.append(
            NodeEvidence(
                node_id=n["id"],
                label=n.get("name") or n["id"],
                evidence=ev,
                stages=stages,
                connectivity=n.get("connectivity"),
                profile="standard",
                physical_cores=n.get("physical_cores"),
                logical_cpus=n.get("logical_cpus"),
                hardware_score=n.get("hardware_score"),
            )
        )
    return out
