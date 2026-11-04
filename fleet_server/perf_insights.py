"""Deterministic performance intelligence insights."""

from __future__ import annotations

from typing import Any

RULE_VERSION = "1.0"

WEAK_SPEEDUP_FLOOR = 2.0
WEAK_SPEEDUP_WORKER_FACTOR = 0.35
GOOD_SPEEDUP_THRESHOLD = 3.5


def _insight(
    rule_id: str,
    severity: str,
    scope: dict[str, Any],
    observation: str,
    meaning: str,
    action: str,
    *,
    action_link: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dedupe = rule_id + ":" + ":".join(f"{k}={v}" for k, v in sorted(scope.items()))
    return {
        "rule_id": rule_id,
        "rule_version": RULE_VERSION,
        "severity": severity,
        "scope": scope,
        "observation": observation,
        "meaning": meaning,
        "recommended_action": action,
        "action": action_link or {},
        "evidence": evidence or {},
        "dedupe_key": dedupe,
    }


def evaluate_insights(score_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate all rules against a compute_score / performance_score_view document."""
    findings: list[dict[str, Any]] = []
    if not score_doc.get("ok"):
        return findings

    baseline = score_doc.get("baseline") if isinstance(score_doc.get("baseline"), dict) else {}
    cluster = score_doc.get("cluster") if isinstance(score_doc.get("cluster"), dict) else {}
    nodes = score_doc.get("nodes") if isinstance(score_doc.get("nodes"), list) else []
    components = score_doc.get("components") if isinstance(score_doc.get("components"), dict) else {}
    include_snapshots = bool(score_doc.get("include_snapshots"))

    if baseline.get("status") == "not_measured":
        findings.append(
            _insight(
                "REFERENCE_MISSING",
                "blocker",
                {"baseline_node_id": baseline.get("node_id")},
                f"Baseline {baseline.get('label') or baseline.get('node_id')} does not have complete comparable stage rates.",
                "Scores relative to that reference cannot be calculated until a matching Market Studio standard run exists.",
                "Run the standard profile on the chosen baseline host or select another eligible reference node.",
                action_link={"kind": "run_market_studio", "profile": "standard", "peer_id": baseline.get("node_id")},
            )
        )

    findings.append(
        _insight(
            "DISTRIBUTED_NOT_MEASURED",
            "info",
            {"cluster": "all"},
            "Modeled cluster capacity is available from standalone multi-worker rates.",
            "Network scheduling and shared-resource effects on real distributed throughput have not been measured.",
            "Run a coordinated multi-node workload test that records both predicted additive capacity and achieved throughput.",
            evidence={"modeled_composite": cluster.get("composite")},
        )
    )

    for node in nodes:
        node_id = str(node.get("node_id") or "")
        label = str(node.get("label") or node_id)
        evidence_state = node.get("evidence")
        connectivity = node.get("connectivity")
        components_node = node.get("components") if isinstance(node.get("components"), dict) else {}

        if evidence_state in {"not_run", "unavailable"} and node.get("composite") is None:
            findings.append(
                _insight(
                    "MISSING_STAGE_RUN",
                    "attention",
                    {"node_id": node_id},
                    f"{label}: no comparable Market Studio stage rates are recorded"
                    + (f" (latest reachability: {connectivity})" if connectivity else "") + ".",
                    "Cluster capacity uses only measured nodes; this host is not treated as zero performance.",
                    "Check reachability and run a scoped Market Studio standard benchmark on this node.",
                    action_link={"kind": "run_market_studio", "profile": "standard", "peer_id": node_id},
                )
            )
            continue

        if evidence_state == "saved_snapshot" and connectivity:
            findings.append(
                _insight(
                    "SAVED_ONLY_WITH_AUTH_FAILURE",
                    "attention",
                    {"node_id": node_id},
                    f"{label} has saved stage rates while live status reports {connectivity}.",
                    "Including this node changes the capacity model using historical evidence that is not currently verified live.",
                    "Verify access, re-run a comparable standard profile, or exclude saved snapshots for a confirmed-only view.",
                    action_link={"kind": "open_scoring", "toggle": "include_snapshots"},
                    evidence={"connectivity": connectivity, "include_snapshots": include_snapshots},
                )
            )

        if node.get("worker_oversubscription"):
            duck = components_node.get("duckdb") if isinstance(components_node.get("duckdb"), dict) else {}
            workers = duck.get("max_workers")
            cpus = node.get("logical_cpus")
            findings.append(
                _insight(
                    "WORKER_OVERSUBSCRIPTION",
                    "attention",
                    {"node_id": node_id, "workload": "duckdb"},
                    f"{label} reports {workers} benchmark workers versus {cpus} logical CPUs.",
                    "Extra workers may contend for CPU; the recorded configuration should be validated before interpreting efficiency.",
                    "Run a 1/2/4/8 worker sweep on the same fixture and capture process utilization.",
                    action_link={"kind": "run_market_studio", "profile": "standard", "peer_id": node_id},
                    evidence={"max_workers": workers, "logical_cpus": cpus},
                )
            )

        for sid, comp in components_node.items():
            if not isinstance(comp, dict):
                continue
            mw = comp.get("max_workers")
            speedup = comp.get("speedup")
            if speedup and mw is None:
                findings.append(
                    _insight(
                        "UNKNOWN_WORKER_COUNT",
                        "info",
                        {"node_id": node_id, "workload": sid},
                        f"{label} {sid}: max-worker rate is recorded but worker count was not captured.",
                        "Speedup is shown; normalized worker efficiency is not available.",
                        "Record worker settings on the next benchmark run.",
                        evidence={"speedup": speedup, "max_rate": comp.get("max_rate")},
                    )
                )
            if speedup and mw and speedup < min(WEAK_SPEEDUP_FLOOR, WEAK_SPEEDUP_WORKER_FACTOR * float(mw)):
                findings.append(
                    _insight(
                        "WEAK_PARALLEL_SPEEDUP",
                        "attention",
                        {"node_id": node_id, "workload": sid},
                        f"{label} {sid}: speedup {speedup:.2f}× with {mw} reported workers.",
                        "Additional workers added limited throughput in this fixture; the measurement alone does not identify the limiter.",
                        "Run a worker sweep with identical fixture size and capture stage breakdown.",
                        evidence={"speedup": speedup, "max_workers": mw},
                    )
                )
            if speedup and mw and speedup >= GOOD_SPEEDUP_THRESHOLD:
                findings.append(
                    _insight(
                        "GOOD_SCALING",
                        "info",
                        {"node_id": node_id, "workload": sid},
                        f"{label} {sid}: speedup {speedup:.2f}× from one to {mw} workers in this sample.",
                        "Throughput scales well relative to weaker stages in this dataset; repeat under production-like load before relying on it.",
                        "Verify repeatability with a larger dataset or longer run duration.",
                        evidence={"speedup": speedup, "max_workers": mw},
                    )
                )

        if node.get("exclusion_reason") == "incompatible_profile":
            findings.append(
                _insight(
                    "EVIDENCE_INCOMPATIBLE",
                    "attention",
                    {"node_id": node_id},
                    f"{label}: displayed Market Studio result uses a non-standard profile.",
                    "Cross-node arithmetic requires the standard comparison profile.",
                    "Re-run Market Studio with profile standard on this node.",
                    action_link={"kind": "run_market_studio", "profile": "standard", "peer_id": node_id},
                )
            )

    if components:
        ranked = sorted(
            ((sid, entry.get("cluster_index")) for sid, entry in components.items() if isinstance(entry, dict)),
            key=lambda item: (item[1] is None, item[1] or 0),
        )
        if ranked and ranked[0][1] is not None:
            low_sid, low_val = ranked[0]
            findings.append(
                _insight(
                    "STAGE_CAPACITY_LOW",
                    "info",
                    {"workload": low_sid},
                    f"Lowest cluster component index among measured stages is {low_sid} at {float(low_val):.1f} (baseline=100 per stage).",
                    "For the selected nodes and weights, this workload adds relatively less modeled capacity than other stages.",
                    "Confirm fixture comparability and test concurrency settings for that workload.",
                    evidence={"cluster_index": low_val, "stage": low_sid},
                )
            )
        if ranked and ranked[-1][1] is not None:
            hi_sid, hi_val = ranked[-1]
            findings.append(
                _insight(
                    "STAGE_CAPACITY_STRONG",
                    "info",
                    {"workload": hi_sid},
                    f"Highest cluster component index is {hi_sid} at {float(hi_val):.1f} relative to the baseline stage.",
                    "Included nodes show relatively large standalone capacity for this workload versus the reference; this is not verified distributed throughput.",
                    "Validate at cluster level before scheduling partition-sensitive work solely on this strength.",
                    evidence={"cluster_index": hi_val, "stage": hi_sid},
                )
            )

    order = {"blocker": 0, "attention": 1, "info": 2}
    return sorted(findings, key=lambda f: (order.get(f.get("severity"), 9), f.get("rule_id", "")))


def _prioritize(findings: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    order = {"blocker": 0, "attention": 1, "info": 2}
    sorted_findings = sorted(findings, key=lambda f: (order.get(f.get("severity"), 9), f.get("rule_id", "")))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in sorted_findings:
        key = item.get("dedupe_key") or item.get("rule_id")
        if key in seen:
            continue
        seen.add(str(key))
        out.append(item)
        if len(out) >= limit:
            break
    return out


def evaluate_insights_prioritized(score_doc: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    return _prioritize(evaluate_insights(score_doc), limit=limit)
