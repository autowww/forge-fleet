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


def test_engine_lines_are_not_lost_under_later_container_status() -> None:
    text = "[benchmark] postgres SQL + concurrency\n" + ("Container postgres Healthy\n" * 200)
    redacted = fmsbench_runs.redact_log(text)
    assert "[benchmark] postgres" in redacted
    assert fmsbench_runs.phases_from_log(redacted)["postgres_sql"] is True
    assert fmsbench_runs.current_phase(text) == "PostgreSQL SQL and concurrency"
    assert len(fmsbench_runs.clip_log(text)) <= 4000


def test_docker_command_uses_the_docker_group_when_needed(monkeypatch) -> None:
    def fake_run(argv, **_kwargs):
        class Result:
            pass
        out = Result()
        out.stderr = ""
        if argv[0] == "docker":
            out.returncode = 1
            out.stdout = ""
        else:
            out.returncode = 0
            out.stdout = "29.1.3\n"
        return out

    monkeypatch.setattr(fmsbench_runs.subprocess, "run", fake_run)
    launched = fmsbench_runs._docker_command(["./run.sh", "--profile", "standard"])
    assert launched[:3] == ["sg", "docker", "-c"]
    assert "run.sh" in launched[3]


def _scored_view(wall: float, single: float, double: float) -> dict:
    stages = {}
    for name in ("postgres", "duckdb", "sqlite", "compute"):
        stages[name] = {
            "single": {"rate": single, "seconds": 1.0},
            "double": {"rate": double, "seconds": 1.0},
            "stage_seconds": 2.0,
        }
    return {"wall_seconds": wall, "stages": {"wall_seconds": wall, "stages": stages}}


def test_stage_breakdown_keeps_one_and_two_threads() -> None:
    report = {
        "start_utc": "2026-10-25T00:00:00+00:00",
        "end_utc": "2026-10-25T00:01:00+00:00",
        "hardware": {"host_logical_cpus": 12},
        "engines": {
            "postgres": {
                "prep_seconds": 2.0,
                "concurrency": {"scales": {
                    "1": {"median_jobs_per_second": 1.5, "trials": [{"elapsed_seconds": 5.0}]},
                    "2": {"median_jobs_per_second": 3.0, "trials": [{"elapsed_seconds": 5.0}]},
                }},
            }
        },
        "compute": {"loops": 4, "size": 100, "scales": {
            "1": {"median_rows_per_second": 1000.0, "elapsed_seconds": 1.2},
            "2": {"median_rows_per_second": 1800.0, "elapsed_seconds": 1.4},
        }},
    }
    view = fmsbench_runs.stage_breakdown(report)
    assert view is not None
    assert view["wall_seconds"] == 60
    assert view["stages"]["postgres"]["single"]["rate"] == 1.5
    assert view["stages"]["postgres"]["double"]["seconds"] == 5.0
    assert view["stages"]["postgres"]["stage_seconds"] == 12.0
    assert view["stages"]["compute"]["double"]["seconds"] == 1.4


def test_composite_reference_is_100_and_favors_shorter_multithreaded_runs() -> None:
    ref = _scored_view(100, 2, 4)
    assert fmsbench_runs.composite_score(ref, ref) == 100
    quicker = fmsbench_runs.composite_score(ref, _scored_view(50, 2, 8))
    slower = fmsbench_runs.composite_score(ref, _scored_view(200, 2, 4))
    assert quicker is not None and quicker > 100
    assert slower is not None and slower < 100
    incomplete = _scored_view(100, 2, 4)
    incomplete["stages"]["stages"]["compute"]["double"] = None
    assert fmsbench_runs.composite_score(ref, incomplete) is None


def test_stress_score_is_separate() -> None:
    def stress(wall: float, rate: float) -> dict:
        out = {"wall_seconds": wall}
        for name in ("postgres", "duckdb", "sqlite", "compute"):
            out[name] = {"rate": rate, "seconds": 5}
        return out

    assert fmsbench_runs.stress_score(stress(40, 2), stress(40, 2)) == 100
    assert fmsbench_runs.stress_score(stress(40, 2), stress(40, 4)) > 100
    assert fmsbench_runs.stress_score(stress(40, 2), {"wall_seconds": 40}) is None


def test_stress_result_does_not_replace_the_standard_summary(tmp_path: Path) -> None:
    fmsbench_runs.save_result(tmp_path, {
        "status": "passed",
        "profile": "standard",
        "summary": {"postgres_jobs_per_second": 3},
    })
    fmsbench_runs._save_stress(tmp_path, {
        "threads": 8,
        "wall_seconds": 10,
        "postgres": {"rate": 1},
        "duckdb": {"rate": 1},
        "sqlite": {"rate": 1},
        "compute": {"rate": 1},
    }, log_excerpt="stress done")
    saved = json.loads(fmsbench_runs.result_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["status"] == "passed"
    assert saved["summary"]["postgres_jobs_per_second"] == 3
    assert saved["stress_status"] == "passed"
    assert saved["stress"]["threads"] == 8


def test_capacity_reports_cores_threads_and_stress_width() -> None:
    cap = fmsbench_runs.host_capacity({"physical_cpus": 6, "logical_cpus": 12})
    assert cap["physical_cores"] == 6
    assert cap["hardware_threads"] == 12
    assert cap["multiprocess_max"] == 12
    assert cap["stress_threads"] == 24


def test_cleanup_keeps_result_json_and_removes_work_files(tmp_path: Path) -> None:
    suite = tmp_path / "fmsbench-suite"
    work = suite / "work" / "standard-x"
    work.mkdir(parents=True)
    (work / "bars.csv").write_text("id\n", encoding="utf-8")
    (suite / ".env").write_text("FMSBENCH_PASSWORD=secret\n", encoding="utf-8")
    results = suite / "results"
    results.mkdir()
    (results / "fmsbench-node.json").write_text("{}\n", encoding="utf-8")
    (results / "preflight-last.json").write_text("{}\n", encoding="utf-8")
    seen: list[list[str]] = []

    def run_cmd(argv: list[str]) -> tuple[int, str]:
        seen.append(argv)
        return 0, ""

    report = fmsbench_runs.cleanup_runtime(suite, run_cmd=run_cmd)
    assert report["ok"] is True
    assert report["kept_results"] == ["fmsbench-node.json"]
    assert not work.exists()
    assert not (suite / ".env").exists()
    assert not (results / "preflight-last.json").exists()
    assert (results / "fmsbench-node.json").is_file()
    assert seen and seen[0][:4] == ["docker", "compose", "-p", report["project"]]


def test_market_result_is_archived_and_missing_peer_uses_the_saved_row(tmp_path: Path) -> None:
    suite_results = tmp_path / "fmsbench-suite" / "results"
    suite_results.mkdir(parents=True)
    (suite_results / "fmsbench-node.json").write_text('{"status":"passed"}\n', encoding="utf-8")
    fmsbench_runs._finish(
        tmp_path,
        "standard",
        "passed",
        result_name="fmsbench-node.json",
        summary={"postgres_jobs_per_second": 3},
    )
    archived = tmp_path / "etc" / "forge-benchmarks" / "reports" / "fmsbench-node.json"
    assert archived.is_file()
    history = (tmp_path / "etc" / "forge-benchmarks" / "market-studio.jsonl").read_text(encoding="utf-8")
    assert "standard" in history
    saved = {
        "peer_id": "mercury",
        "label": "Mercury",
        "fleet": {"fleet_mark": 10},
        "fmsbench": {"status": "passed", "summary": {"postgres_jobs_per_second": 2}},
    }
    etc = tmp_path / "etc"
    etc.mkdir(parents=True, exist_ok=True)
    (etc / "remote-peers.json").write_text(json.dumps({"peers": [
        {"id": "mercury", "label": "Mercury", "base_url": "https://example.invalid", "bearer_token": "x"},
    ]}), encoding="utf-8")
    (tmp_path / "etc" / "forge-benchmarks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "etc" / "forge-benchmarks" / "mesh-snapshot.json").write_text(
        json.dumps({"mercury": {"saved_at": 1, "row": saved}}),
        encoding="utf-8",
    )

    def fetch(_peer_id: str) -> tuple[int, dict | None]:
        return 502, None

    doc = fmsbench_runs.comparison(tmp_path, fetch_peer=fetch)
    mercury = next(row for row in doc["rows"] if row["peer_id"] == "mercury")
    assert mercury["from_saved"] is True
    assert mercury["fleet"]["fleet_mark"] == 10
    assert mercury["fmsbench"]["status"] == "passed"
    assert mercury["live_error"] == "http_502"


def test_batch_starts_every_peer_without_replacing_scores(tmp_path: Path) -> None:
    peers = tmp_path / "etc"
    peers.mkdir()
    (peers / "remote-peers.json").write_text(json.dumps({"peers": [
        {"id": "mercury", "label": "Mercury", "base_url": "https://example.invalid", "bearer_token": "x"},
    ]}), encoding="utf-8")
    host_profile.save_profile(tmp_path, {"benchmark": {"fleet_mark": 42, "bench_version": 2}})
    launched: list[str] = []

    def launch(_data: Path, peer_id: str, suite: str, profile: str) -> dict:
        launched.append(f"{suite}:{profile}:{peer_id}")
        return {"ok": True}

    def spawn(job) -> None:
        job()

    out, code = fmsbench_runs.start_batch(
        tmp_path, "market_studio", profile="standard", launch=launch, spawn=spawn,
    )
    assert code == 202
    assert out["status"] == "finished"
    assert launched == ["market_studio:standard:local", "market_studio:standard:mercury"]
    saved = host_profile.load_profile(tmp_path)
    assert saved["benchmark"]["fleet_mark"] == 42


def test_host_max_uses_physical_cores_and_hardware_threads(monkeypatch) -> None:
    monkeypatch.setattr(
        host_profile,
        "static_hardware",
        lambda: {"physical_cpus": 8, "logical_cpus": 16},
    )
    cores = fmsbench_runs._run_command("host-max-cores")
    threads = fmsbench_runs._run_command("host-max-threads")
    assert cores[cores.index("--threads") + 1] == "8"
    assert cores[cores.index("--workers") + 1] == "8"
    assert threads[threads.index("--threads") + 1] == "16"
    assert threads[threads.index("--workers") + 1] == "16"
    assert cores[cores.index("--profile") + 1] == "standard"
    assert fmsbench_runs._FULL_STEPS == ("standard", "host-max-cores", "host-max-threads", "stress")


def test_host_max_result_keeps_the_standard_summary(tmp_path: Path) -> None:
    fmsbench_runs.save_result(tmp_path, {
        "status": "passed",
        "profile": "standard",
        "summary": {"postgres_jobs_per_second": 4},
    })
    fmsbench_runs._save_width(
        tmp_path,
        "host-max-cores",
        {
            "status": "passed",
            "config": {"threads": 8, "workers": 8},
            "start_utc": "2026-10-25T00:00:00+00:00",
            "end_utc": "2026-10-25T00:01:00+00:00",
            "engines": {},
            "compute": {},
        },
        log_excerpt="host cores done",
    )
    saved = json.loads(fmsbench_runs.result_path(tmp_path).read_text(encoding="utf-8"))
    assert saved["status"] == "passed"
    assert saved["summary"]["postgres_jobs_per_second"] == 4
    assert saved["widths"]["host-max-cores"]["threads"] == 8
    assert saved["width_status"] == "passed"


def test_live_phase_follows_the_log() -> None:
    assert fmsbench_runs.current_phase("") == "Checking the host"
    assert fmsbench_runs.current_phase("[benchmark] sqlite") == "SQLite SQL and concurrency"
    assert fmsbench_runs.current_phase("NumPy numerical compute") == "NumPy compute"


def test_fleet_progress_stays_out_of_the_fleet_mark(tmp_path: Path) -> None:
    host_profile.write_benchmark_progress(tmp_path, {
        "status": "running",
        "kind": "fleet_mark",
        "step": "memory",
        "updated_at": 10**10,
    })
    assert host_profile.load_profile(tmp_path) is None
    seen = host_profile.read_benchmark_progress(tmp_path)
    assert seen is not None
    assert seen["step"] == "memory"
    assert "fmsbench" not in seen


def test_stream_publishes_the_current_phase(tmp_path: Path) -> None:
    import subprocess

    proc = subprocess.Popen(
        ["python3", "-c", "print('[benchmark] duckdb', flush=True)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    fmsbench_runs.save_result(tmp_path, {"status": "running", "started_at": 1, "profile": "micro"})
    log, code = fmsbench_runs._stream_run(tmp_path, "micro", proc, 10)
    assert code == 0
    assert "duckdb" in log
    side = json.loads(fmsbench_runs.result_path(tmp_path).read_text(encoding="utf-8"))
    assert side["status"] == "running"
    assert side["phase"] == "DuckDB SQL and concurrency"
    assert side["started_at"] == 1
    assert "secret" not in side["log_excerpt"]
