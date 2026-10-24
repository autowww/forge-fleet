"""Fleet mark and FMSBench stay in different documents."""

from __future__ import annotations

import json
from pathlib import Path

from fleet_server import fmsbench_runs, host_profile


def test_fleet_document_drops_fmsbench_key() -> None:
    doc = fmsbench_runs.fleet_profile_document(
        {"benchmark": {"fleet_mark": 1}, "fmsbench": {"status": "passed", "summary": {"postgres_jobs_per_second": 9}}, "note": "keep"},
        {"fleet_mark": 50, "bench_version": 2},
        {"node_id": "granite"},
        10.0,
    )
    assert "fmsbench" not in doc
    assert doc["benchmark"]["fleet_mark"] == 50
    assert doc["note"] == "keep"
    assert doc["hardware"]["node_id"] == "granite"


def test_sidecar_does_not_change_fleet_profile(tmp_path: Path) -> None:
    host_profile.save_profile(tmp_path, {"benchmark": {"fleet_mark": 5973, "bench_version": 2}, "measured_at": 11})
    out, code = fmsbench_runs.start_run(
        tmp_path,
        "smoke",
        probe=lambda: {"compose": False, "detail": "docker compose missing"},
    )
    assert code == 503
    assert out["error"] == "compose_unavailable"
    saved = host_profile.load_profile(tmp_path)
    assert saved is not None
    assert saved["benchmark"]["fleet_mark"] == 5973
    assert "fmsbench" not in saved
    side = json.loads(fmsbench_runs.result_path(tmp_path).read_text(encoding="utf-8"))
    assert side["suite"] == "FMSBench"
    assert side["status"] == "failed"
    assert side.get("summary") is None


def test_compare_rows_keep_columns_separate(tmp_path: Path) -> None:
    host_profile.save_profile(
        tmp_path,
        {"benchmark": {"fleet_mark": 100, "bench_version": 2, "fmsbench": {"status": "passed"}}, "hardware": {"node_id": "granite"}, "measured_at": 5},
    )
    fmsbench_runs.save_result(tmp_path, {"suite": "FMSBench", "status": "passed", "profile": "smoke", "summary": {"sqlite_jobs_per_second": 3.5}})

    def fetch(peer_id: str):
        return 200, {
            "hardware": {"node_id": "mercury"},
            "benchmark": {"fleet_mark": 80, "bench_version": 2},
            "measured_at": 6,
            "fmsbench": {"status": "not_run", "suite": "FMSBench"},
        }

    from fleet_server import remote_peers

    remote_peers.upsert_peer(tmp_path, "mercury", label="Mercury", base_url="https://mercury.example", bearer_token="x")
    doc = fmsbench_runs.comparison(tmp_path, fetch_peer=fetch)
    assert doc["rows"][0]["fleet"]["fleet_mark"] == 100
    assert doc["rows"][0]["fmsbench"]["status"] == "passed"
    assert doc["rows"][0]["fmsbench"]["summary"]["sqlite_jobs_per_second"] == 3.5
    assert "fleet_mark" not in doc["rows"][0]["fmsbench"]
    assert doc["rows"][1]["peer_id"] == "mercury"
    assert doc["rows"][1]["fleet"]["fleet_mark"] == 80
    assert doc["rows"][1]["fmsbench"]["status"] == "not_run"


def test_engine_evidence_requires_sql_and_compute() -> None:
    from fleet_server.fleet_bench import RUNTIME

    assert RUNTIME["containers"] is False
    assert RUNTIME["postgresql"] is False
    assert RUNTIME["sql"] is False
    bare = {"status": "passed", "fleet_mark": 5669, "timings": {"cpu_single_s": 0.8}}
    assert fmsbench_runs.report_has_engine_evidence(bare) is False
    log = "\n".join([
        "[prepare] postgres",
        "[benchmark] postgres",
        "[benchmark] duckdb",
        "[benchmark] sqlite",
        "[benchmark] NumPy numerical compute",
        "postgresql://fmsbench:secret@postgres/fmsbench",
    ])
    phases = fmsbench_runs.phases_from_log(log)
    assert phases["postgres_sql"] and phases["numpy_compute"]
    assert "secret" not in fmsbench_runs.redact_log(log)
    full = {
        "status": "passed",
        "engines": {
            name: {"version": "x", "queries": {"market_rollup": {}}}
            for name in ("postgres", "duckdb", "sqlite")
        },
        "compute": {"numpy_version": "2.2.6", "scales": {"1": {}}},
    }
    assert fmsbench_runs.report_has_engine_evidence(full) is True


def test_summary_ignores_fleet_mark() -> None:
    summary = fmsbench_runs.summarize_fms_report(
        {
            "status": "passed",
            "config": {"profile": "smoke"},
            "fleet_mark": 9999,
            "engines": {"postgres": {"concurrency": {"best_jobs_per_second": 4.0}, "ingest": {"rows_per_second": 8.0}}},
            "compute": {"best_rows_per_second": 10.0},
        }
    )
    assert "fleet_mark" not in summary
    assert summary["postgres_jobs_per_second"] == 4.0
    assert summary["compute_rows_per_second"] == 10.0
