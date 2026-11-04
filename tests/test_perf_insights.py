"""Deterministic insight rule tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet_server import perf_insights, perf_scoring


@pytest.fixture
def score_with_snapshots() -> dict:
    fx = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "perf_screenshot_fixture.json").read_text(encoding="utf-8")
    )
    nodes = perf_scoring.handoff_fixture_to_nodes(fx)
    doc = perf_scoring.compute_score(
        nodes,
        perf_scoring.ScoringPolicy(baseline_node_id="precision", include_snapshots=True),
    )
    doc["include_snapshots"] = True
    return doc


def test_distributed_not_measured_always(score_with_snapshots: dict) -> None:
    findings = perf_insights.evaluate_insights(score_with_snapshots)
    assert any(f["rule_id"] == "DISTRIBUTED_NOT_MEASURED" for f in findings)


def test_missing_stage_run_for_venus(score_with_snapshots: dict) -> None:
    findings = perf_insights.evaluate_insights(score_with_snapshots)
    assert any(
        f["rule_id"] == "MISSING_STAGE_RUN" and f["scope"].get("node_id") == "venus" for f in findings
    )


def test_saved_only_auth_failure(score_with_snapshots: dict) -> None:
    findings = perf_insights.evaluate_insights(score_with_snapshots)
    assert any(f["rule_id"] == "SAVED_ONLY_WITH_AUTH_FAILURE" for f in findings)


def test_worker_oversubscription_mercury(score_with_snapshots: dict) -> None:
    findings = perf_insights.evaluate_insights(score_with_snapshots)
    assert any(
        f["rule_id"] == "WORKER_OVERSUBSCRIPTION" and f["scope"].get("node_id") == "mercury" for f in findings
    )


def test_unknown_worker_count_asus(score_with_snapshots: dict) -> None:
    findings = perf_insights.evaluate_insights(score_with_snapshots)
    assert any(f["rule_id"] == "UNKNOWN_WORKER_COUNT" for f in findings)


def test_reference_missing_on_bad_baseline() -> None:
    doc = {
        "ok": True,
        "baseline": {"node_id": "granite", "label": "Granite", "status": "not_measured"},
        "cluster": {},
        "nodes": [],
        "components": {},
    }
    findings = perf_insights.evaluate_insights(doc)
    assert findings[0]["rule_id"] == "REFERENCE_MISSING"


def test_insight_fields_complete(score_with_snapshots: dict) -> None:
    for item in perf_insights.evaluate_insights(score_with_snapshots):
        assert item.get("observation")
        assert item.get("meaning")
        assert item.get("recommended_action")
        assert item.get("rule_id")
