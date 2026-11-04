"""Performance intelligence scoring domain tests (handoff oracle parity)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet_server import perf_scoring

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "perf_screenshot_fixture.json"


@pytest.fixture
def fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def oracle_result(fx: dict) -> dict:
    return perf_scoring.compute_from_handoff_fixture(fx)


def test_baseline_is_exactly_100(oracle_result: dict) -> None:
    assert oracle_result["node_composites"]["precision"] == pytest.approx(100, abs=1e-6)
    for v in oracle_result["node_component_indexes"]["precision"].values():
        assert v == pytest.approx(100, abs=1e-6)


def test_cluster_expected_and_node_scores(oracle_result: dict) -> None:
    assert oracle_result["node_composites"]["mercury"] == pytest.approx(35.0094656222, abs=1e-6)
    assert oracle_result["node_composites"]["asus"] == pytest.approx(42.5016745384, abs=1e-6)
    assert oracle_result["cluster_composite"] == pytest.approx(177.5111401607, abs=1e-6)


def test_stage_scores(oracle_result: dict) -> None:
    expectations = {
        "postgresql": 159.9290780142,
        "duckdb": 162.4062319677,
        "sqlite": 151.3368983957,
        "numpy": 190.0879071756,
        "nlp": 210.3884262355,
    }
    for stage, score in expectations.items():
        assert oracle_result["component_indexes"][stage] == pytest.approx(score, abs=1e-6)


def test_contributions_sum_and_node_sum(oracle_result: dict) -> None:
    r = oracle_result
    assert sum(r["component_contributions"].values()) == pytest.approx(r["cluster_composite"], abs=1e-6)
    assert sum(r["node_composites"].values()) == pytest.approx(r["cluster_composite"], abs=1e-6)


def test_exclude_snapshot(fx: dict) -> None:
    r = perf_scoring.compute_from_handoff_fixture(fx, include_snapshots=False)
    assert r["included_nodes"] == ["precision", "mercury"]
    assert r["cluster_composite"] == pytest.approx(135.0094656222, abs=1e-6)
    assert "asus" not in r["node_composites"]


def test_missing_venus_is_unknown_not_measured_zero(oracle_result: dict) -> None:
    assert "venus" not in oracle_result["node_composites"]
    assert "venus" in oracle_result["excluded_unmeasured_nodes"]


def test_scaling_calculation(oracle_result: dict) -> None:
    assert oracle_result["speedups"]["precision"]["duckdb"] == pytest.approx(69.32 / 11.69, abs=1e-6)
    assert oracle_result["worker_efficiencies"]["precision"]["duckdb"] == pytest.approx(
        (69.32 / 11.69) / 8, abs=1e-6
    )
    assert oracle_result["worker_efficiencies"]["asus"]["duckdb"] is None


def test_oversubscribed_mercury_not_silently_corrected(fx: dict, oracle_result: dict) -> None:
    assert fx["nodes"][1]["logical_cpus"] == 4
    assert fx["nodes"][1]["rate"]["duckdb"]["max_workers"] == 8
    assert oracle_result["speedups"]["mercury"]["duckdb"] == pytest.approx(15.71 / 8.73)


def test_granite_not_fabricated(fx: dict) -> None:
    with pytest.raises(ValueError):
        perf_scoring.compute_from_handoff_fixture(fx, baseline_node_id="granite")


def test_weights_reweighted(fx: dict) -> None:
    r = perf_scoring.compute_from_handoff_fixture(
        fx,
        weight_overrides={"postgresql": 100, "duckdb": 0, "sqlite": 0, "numpy": 0, "nlp": 0},
    )
    assert r["cluster_composite"] == pytest.approx(r["component_indexes"]["postgresql"], abs=1e-6)
    assert sum(r["weights"].values()) == pytest.approx(1.0)


def test_invalid_weights_rejected(fx: dict) -> None:
    with pytest.raises(ValueError):
        perf_scoring.compute_from_handoff_fixture(fx, weight_overrides={"postgresql": -1})
    with pytest.raises(ValueError):
        perf_scoring.compute_from_handoff_fixture(
            fx,
            weight_overrides={k: 0 for k in ["postgresql", "duckdb", "sqlite", "numpy", "nlp"]},
        )


def test_compute_score_trust_first_headline(fx: dict) -> None:
    nodes = perf_scoring.handoff_fixture_to_nodes(fx)
    policy = perf_scoring.ScoringPolicy(
        baseline_node_id="precision",
        include_snapshots=False,
    )
    doc = perf_scoring.compute_score(nodes, policy)
    assert doc["cluster"]["composite_confirmed"] == pytest.approx(135.0094656222, abs=1e-4)
    assert doc["cluster"]["composite_with_snapshots"] == pytest.approx(177.5111401607, abs=1e-4)
    assert doc["cluster"]["composite"] == pytest.approx(135.0094656222, abs=1e-4)


def test_compute_score_with_snapshots_toggle(fx: dict) -> None:
    nodes = perf_scoring.handoff_fixture_to_nodes(fx)
    policy = perf_scoring.ScoringPolicy(baseline_node_id="precision", include_snapshots=True)
    doc = perf_scoring.compute_score(nodes, policy)
    assert doc["cluster"]["composite"] == pytest.approx(177.5111401607, abs=1e-4)


def test_venus_not_scored_in_view_model(fx: dict) -> None:
    nodes = perf_scoring.handoff_fixture_to_nodes(fx)
    doc = perf_scoring.compute_score(
        nodes,
        perf_scoring.ScoringPolicy(baseline_node_id="precision", include_snapshots=True),
    )
    venus = next(n for n in doc["nodes"] if n["node_id"] == "venus")
    assert venus["composite"] is None
    assert venus["included_in_cluster"] is False
