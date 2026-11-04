"""Performance score API and row adapter tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet_server import fmsbench_runs, host_profile, perf_scoring


def _scored_view(wall: float, single: float, double: float, threads: int = 8) -> dict:
    stages = {}
    for name in ("postgres", "duckdb", "sqlite", "compute", "nlp"):
        stages[name] = {
            "single": {"rate": single, "seconds": 1.0},
            "double": {"rate": double, "seconds": 1.0},
            "multi": {"rate": double, "seconds": 1.0, "threads": threads},
            "stage_seconds": 2.0,
        }
    return {
        "wall_seconds": wall,
        "stages": {"wall_seconds": wall, "stages": stages},
    }


def test_evidence_from_rows_saved_and_auth(tmp_path: Path) -> None:
    rows = [
        {
            "peer_id": "asus",
            "label": "ASUS",
            "from_saved": True,
            "live_error": "http_401",
            "fmsbench": {
                "status": "passed",
                "profile": "standard",
                "stages": _scored_view(100, 1.0, 2.0, threads=8),
                "result_name": "fmsbench-asus.json",
            },
            "capacity": {"physical_cores": 10, "hardware_threads": 12},
            "fleet": {"fleet_mark": 2093},
        }
    ]
    nodes = fmsbench_runs.evidence_from_rows(rows)
    assert len(nodes) == 1
    assert nodes[0].evidence == "saved_snapshot"
    assert nodes[0].connectivity == "http_401"


def test_evidence_smoke_profile_incompatible() -> None:
    rows = [
        {
            "peer_id": "local",
            "label": "local",
            "fmsbench": {"status": "passed", "profile": "smoke", "stages": _scored_view(10, 1, 2)},
            "capacity": {},
            "fleet": {},
        }
    ]
    nodes = fmsbench_runs.evidence_from_rows(rows)
    assert nodes[0].evidence == "incompatible"


def test_performance_score_view_from_fixture_rows() -> None:
    fx = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "perf_screenshot_fixture.json").read_text(encoding="utf-8")
    )
    handoff_nodes = perf_scoring.handoff_fixture_to_nodes(fx)

    def row_from_handoff(node: perf_scoring.NodeEvidence) -> dict:
        stages = {}
        inner = {}
        reverse = {v: k for k, v in fmsbench_runs._FMS_STAGE_TO_DOMAIN.items()}
        for sid, st in node.stages.items():
            fms_key = reverse[sid]
            inner[fms_key] = {
                "single": {"rate": st.single},
                "multi": {"rate": st.max_rate, "threads": st.max_workers},
            }
        stages = {"stages": inner}
        return {
            "peer_id": node.node_id,
            "label": node.label,
            "from_saved": node.evidence == "saved_snapshot",
            "live_error": node.connectivity,
            "fmsbench": {
                "status": "passed" if node.stages else "not_run",
                "profile": "standard",
                "stages": stages,
            },
            "capacity": {
                "physical_cores": node.physical_cores,
                "hardware_threads": node.logical_cpus,
            },
            "fleet": {"fleet_mark": node.hardware_score},
        }

    rows = [row_from_handoff(n) for n in handoff_nodes if n.node_id != "venus"]
    rows.append(
        {
            "peer_id": "venus",
            "label": "Venus",
            "error": "http_502",
            "fmsbench": {"status": "unavailable", "suite": "FMSBench"},
            "capacity": {},
            "fleet": {},
        }
    )
    nodes = fmsbench_runs.evidence_from_rows(rows)
    policy = perf_scoring.ScoringPolicy(baseline_node_id="precision", include_snapshots=True)
    doc = perf_scoring.compute_score(nodes, policy)
    assert doc["cluster"]["composite"] == pytest.approx(177.5111401607, abs=1e-3)


def test_comparison_includes_scoring_version(tmp_path: Path) -> None:
    host_profile.save_profile(tmp_path, {"benchmark": {"fleet_mark": 100, "bench_version": 2}})
    doc = fmsbench_runs.comparison(tmp_path)
    assert doc.get("perf_scoring_version") == "1.0"
