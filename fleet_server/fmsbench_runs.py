"""Market Studio benchmark runs, stored apart from the Fleet mark.

The Fleet mark lives in ``etc/host-profile.json`` under ``benchmark``.
This module writes only ``etc/fmsbench-result.json`` and ``fmsbench-suite/``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import select
import shlex
import shutil
import socket
import statistics
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SUITE = "FMSBench"
SUITE_VERSION = "0.2.0"
_RESULT = "fmsbench-result.json"
_SUITE_DIR = "fmsbench-suite"
_BUNDLE_FILES = (
    "bench_v2.py",
    "rank_v2.py",
    "preflight.py",
    "run.sh",
    "compose.yaml",
    "Dockerfile",
    "requirements.txt",
    ".dockerignore",
)
_FLAGS = {
    "micro": ("--threads", "2", "--workers", "2", "--repeats", "1", "--trials", "1", "--duration", "1"),
    "smoke": ("--threads", "2", "--workers", "2", "--repeats", "1", "--trials", "1", "--duration", "1"),
    "standard": ("--threads", "8", "--workers", "8", "--repeats", "3", "--trials", "3", "--duration", "5"),
    "large": ("--threads", "8", "--workers", "8", "--repeats", "3", "--trials", "3", "--duration", "5"),
    "stress": ("--stress-only",),
}
_TIMEOUT_S = {"micro": 600, "smoke": 1200, "standard": 7200, "large": 14400, "stress": 7200}
# Overall time and two-thread throughput dominate. One thread is the smaller share.
COMPOSITE_WEIGHTS = {"overall_time": 0.50, "multithread": 0.35, "singlethread": 0.15}
STRESS_WEIGHTS = {"overall_time": 0.40, "oversubscribed": 0.60}
_STALE_S = 4 * 3600
_lock = threading.Lock()


def bundle_dir() -> Path:
    return Path(__file__).resolve().parent / "fmsbench_bundle"


def result_path(data_dir: Path) -> Path:
    return data_dir / "etc" / _RESULT


def load_result(data_dir: Path) -> dict[str, Any] | None:
    path = result_path(data_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_result(data_dir: Path, doc: dict[str, Any]) -> None:
    path = result_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _benchmarks_dir(data_dir: Path) -> Path:
    path = data_dir / "etc" / "forge-benchmarks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _append_history(data_dir: Path, kind: str, record: dict[str, Any]) -> None:
    path = _benchmarks_dir(data_dir) / f"{kind}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def record_hardware(data_dir: Path, bench: dict[str, Any], measured_at: float) -> None:
    """Keep every hardware score. The host profile still stores only the latest."""
    _append_history(data_dir, "hardware", {
        "saved_at": measured_at,
        "fleet_mark": bench.get("fleet_mark"),
        "cpu_single_mark": bench.get("cpu_single_mark"),
        "cpu_multi_mark": bench.get("cpu_multi_mark"),
        "memory_mark": bench.get("memory_mark"),
        "disk_mark": bench.get("disk_mark"),
        "bench_version": bench.get("bench_version"),
        "timings": bench.get("timings"),
    })


def _archive_report(data_dir: Path, name: Any) -> None:
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        return
    src = data_dir / _SUITE_DIR / "results" / name
    if not src.is_file():
        return
    dest = _benchmarks_dir(data_dir) / "reports" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    if not dest.is_file() or dest.read_bytes() != data:
        dest.write_bytes(data)


def public_view(data_dir: Path) -> dict[str, Any]:
    doc = load_result(data_dir)
    if not doc:
        return {"suite": SUITE, "suite_version": SUITE_VERSION, "status": "not_run"}
    view = {
        "suite": SUITE,
        "suite_version": str(doc.get("suite_version") or SUITE_VERSION),
        "status": str(doc.get("status") or "not_run"),
        "profile": doc.get("profile"),
        "node": doc.get("node"),
        "started_at": doc.get("started_at"),
        "finished_at": doc.get("finished_at"),
        "error": doc.get("error"),
        "detail": doc.get("detail"),
        "result_name": doc.get("result_name"),
        "summary": doc.get("summary") if isinstance(doc.get("summary"), dict) else None,
        "phase": doc.get("phase"),
        "phases": doc.get("phases") if isinstance(doc.get("phases"), dict) else None,
        "heartbeat_at": doc.get("heartbeat_at"),
        "log_excerpt": doc.get("log_excerpt"),
        "stress": doc.get("stress") if isinstance(doc.get("stress"), dict) else None,
        "stress_status": doc.get("stress_status"),
        "stress_started_at": doc.get("stress_started_at"),
        "stress_error": doc.get("stress_error"),
    }
    report = _load_saved_report(data_dir, doc.get("result_name"))
    if report is not None:
        view["stages"] = stage_breakdown(report)
        wall = _wall_seconds(report)
        if wall is not None:
            view["wall_seconds"] = wall
    return {k: v for k, v in view.items() if v is not None}


def redact_log(text: str) -> str:
    kept = []
    for line in (text or "").splitlines():
        upper = line.upper()
        if "PASSWORD" in upper or "POSTGRESQL://" in upper or "SECRET" in upper:
            continue
        kept.append(line)
    return "\n".join(kept)


def clip_log(text: str, limit: int = 4000) -> str:
    return (text or "")[-limit:]


_PHASE_ORDER = (
    "Checking the host",
    "Pulling the PostgreSQL image",
    "Building the runner image",
    "Starting PostgreSQL",
    "Loading data into PostgreSQL",
    "PostgreSQL SQL and concurrency",
    "Loading DuckDB",
    "DuckDB SQL and concurrency",
    "Loading SQLite",
    "SQLite SQL and concurrency",
    "NumPy compute",
    "Saving the result",
)


def current_phase(text: str) -> str:
    phase = _PHASE_ORDER[0]
    rank = 0
    for line in (text or "").splitlines():
        low = line.lower()
        nxt = None
        if "preflight" in low:
            nxt = "Checking the host"
        if "pulling" in low or "pull complete" in low:
            nxt = "Pulling the PostgreSQL image"
        if "building" in low or "exporting to image" in low or low.startswith("#"):
            nxt = "Building the runner image"
        if "waiting" in low or "healthy" in low:
            nxt = "Starting PostgreSQL"
        if "[prepare] postgres" in low:
            nxt = "Loading data into PostgreSQL"
        if "[benchmark] postgres" in low or "wal-on" in low:
            nxt = "PostgreSQL SQL and concurrency"
        if "[prepare] duckdb" in low:
            nxt = "Loading DuckDB"
        if "[benchmark] duckdb" in low:
            nxt = "DuckDB SQL and concurrency"
        if "[prepare] sqlite" in low:
            nxt = "Loading SQLite"
        if "[benchmark] sqlite" in low:
            nxt = "SQLite SQL and concurrency"
        if "numpy numerical" in low or "numpy stress" in low:
            nxt = "NumPy compute"
        if "stress" in low and "postgres" in low:
            nxt = "PostgreSQL SQL and concurrency"
        if "stress" in low and "duckdb" in low:
            nxt = "DuckDB SQL and concurrency"
        if "stress" in low and "sqlite" in low:
            nxt = "SQLite SQL and concurrency"
        if "passed, json" in low:
            nxt = "Saving the result"
        if nxt is None:
            continue
        nxt_rank = _PHASE_ORDER.index(nxt)
        if nxt_rank >= rank:
            phase = nxt
            rank = nxt_rank
    return phase


def phases_from_log(text: str) -> dict[str, bool]:
    log = text or ""
    return {
        "compose_build": "compose build" in log.lower() or "[prepare]" in log,
        "postgres_prepare": "[prepare] postgres" in log,
        "postgres_sql": "[benchmark] postgres" in log,
        "duckdb_sql": "[benchmark] duckdb" in log,
        "sqlite_sql": "[benchmark] sqlite" in log,
        "numpy_compute": "NumPy numerical compute" in log,
        "passed_line": "PASSED, JSON:" in log,
    }


def report_has_engine_evidence(doc: dict[str, Any]) -> bool:
    engines = doc.get("engines") if isinstance(doc.get("engines"), dict) else {}
    for name in ("postgres", "duckdb", "sqlite"):
        eng = engines.get(name) if isinstance(engines.get(name), dict) else {}
        queries = eng.get("queries") if isinstance(eng.get("queries"), dict) else {}
        if not eng.get("version") or "market_rollup" not in queries:
            return False
    compute = doc.get("compute") if isinstance(doc.get("compute"), dict) else {}
    scales = compute.get("scales") if isinstance(compute.get("scales"), dict) else {}
    return bool(compute.get("numpy_version") and scales)


def fleet_profile_document(
    previous: dict[str, Any] | None,
    bench: dict[str, Any],
    hardware: dict[str, Any],
    measured_at: float,
) -> dict[str, Any]:
    """Rebuild the Fleet-mark file without ever keeping an FMSBench payload."""
    prev = previous or {}
    kept = {
        k: v
        for k, v in prev.items()
        if k not in {"benchmark", "hardware", "measured_at", "fmsbench"}
    }
    return {
        **kept,
        "measured_at": measured_at,
        "hardware": hardware,
        "benchmark": bench,
    }


def summarize_fms_report(doc: dict[str, Any]) -> dict[str, Any]:
    engines = doc.get("engines") if isinstance(doc.get("engines"), dict) else {}
    compute = doc.get("compute") if isinstance(doc.get("compute"), dict) else {}

    def bundles(name: str) -> Any:
        eng = engines.get(name) if isinstance(engines.get(name), dict) else {}
        conc = eng.get("concurrency") if isinstance(eng.get("concurrency"), dict) else {}
        return conc.get("best_jobs_per_second")

    postgres = engines.get("postgres") if isinstance(engines.get("postgres"), dict) else {}
    ingest = postgres.get("ingest") if isinstance(postgres.get("ingest"), dict) else {}
    config = doc.get("config") if isinstance(doc.get("config"), dict) else {}
    return {
        "profile": config.get("profile") or doc.get("profile"),
        "node": doc.get("node"),
        "suite_version": doc.get("suite_version"),
        "workload_checksum": doc.get("workload_checksum"),
        "data_revision": doc.get("data_revision"),
        "postgres_jobs_per_second": bundles("postgres"),
        "duckdb_jobs_per_second": bundles("duckdb"),
        "sqlite_jobs_per_second": bundles("sqlite"),
        "postgres_ingest_rows_per_second": ingest.get("rows_per_second"),
        "compute_rows_per_second": compute.get("best_rows_per_second"),
        "status": doc.get("status"),
    }


def host_capacity(hardware: dict[str, Any] | None) -> dict[str, Any]:
    hw = hardware if isinstance(hardware, dict) else {}
    threads = _positive_int(hw.get("logical_cpus"))
    return {
        "physical_cores": hw.get("physical_cpus"),
        "hardware_threads": threads,
        "multiprocess_max": threads,
        "stress_threads": threads * 2 if threads else None,
    }


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 and math.isfinite(number) else None


def _wall_seconds(doc: dict[str, Any]) -> float | None:
    try:
        start = datetime.fromisoformat(str(doc.get("start_utc")))
        end = datetime.fromisoformat(str(doc.get("end_utc")))
    except (TypeError, ValueError):
        return None
    span = (end - start).total_seconds()
    return span if span > 0 else None


def _median_elapsed(scale: dict[str, Any] | None) -> float | None:
    if not isinstance(scale, dict):
        return None
    stored = _positive_float(scale.get("elapsed_seconds"))
    if stored is not None:
        return stored
    trials = scale.get("trials") if isinstance(scale.get("trials"), list) else []
    samples = [_positive_float(item.get("elapsed_seconds")) for item in trials if isinstance(item, dict)]
    samples = [item for item in samples if item is not None]
    if not samples:
        return None
    return float(statistics.median(samples))


def _level(scale: dict[str, Any] | None, rate_key: str) -> dict[str, float] | None:
    if not isinstance(scale, dict):
        return None
    rate = _positive_float(scale.get(rate_key))
    if rate is None:
        return None
    out = {"rate": rate}
    elapsed = _median_elapsed(scale)
    if elapsed is not None:
        out["seconds"] = elapsed
    return out


def _compute_seconds(workers: int, rate: float, loops: int, size: int) -> float | None:
    if rate <= 0 or workers <= 0 or loops <= 0 or size <= 0:
        return None
    return (workers * 3 * loops * size) / rate


def stage_breakdown(doc: dict[str, Any]) -> dict[str, Any] | None:
    engines = doc.get("engines") if isinstance(doc.get("engines"), dict) else {}
    compute = doc.get("compute") if isinstance(doc.get("compute"), dict) else {}
    stages: dict[str, Any] = {}
    for name in ("postgres", "duckdb", "sqlite"):
        eng = engines.get(name) if isinstance(engines.get(name), dict) else {}
        scales = (eng.get("concurrency") or {}).get("scales") if isinstance(eng.get("concurrency"), dict) else {}
        single = _level(scales.get("1") if isinstance(scales, dict) else None, "median_jobs_per_second")
        double = _level(scales.get("2") if isinstance(scales, dict) else None, "median_jobs_per_second")
        if single is None and double is None:
            continue
        prep = _positive_float(eng.get("prep_seconds"))
        pieces = [item.get("seconds") for item in (single, double) if isinstance(item, dict)]
        stage_seconds = sum(piece for piece in pieces if isinstance(piece, (int, float)))
        if prep is not None:
            stage_seconds += prep
        stages[name] = {
            "prep_seconds": prep,
            "single": single,
            "double": double,
            "stage_seconds": stage_seconds if stage_seconds > 0 else None,
        }
    scales = compute.get("scales") if isinstance(compute.get("scales"), dict) else {}
    loops = _positive_int(compute.get("loops")) or 4
    size = _positive_int(compute.get("size")) or 200_000
    single_c = _level(scales.get("1"), "median_rows_per_second")
    double_c = _level(scales.get("2"), "median_rows_per_second")
    if single_c is not None or double_c is not None:
        for workers, level in ((1, single_c), (2, double_c)):
            if isinstance(level, dict) and "seconds" not in level:
                derived = _compute_seconds(workers, level["rate"], loops, size)
                if derived is not None:
                    level["seconds"] = derived
        pieces = [item.get("seconds") for item in (single_c, double_c) if isinstance(item, dict)]
        stage_seconds = sum(piece for piece in pieces if isinstance(piece, (int, float)))
        stages["compute"] = {
            "single": single_c,
            "double": double_c,
            "stage_seconds": stage_seconds if stage_seconds > 0 else None,
        }
    if not stages:
        return None
    hardware = doc.get("hardware") if isinstance(doc.get("hardware"), dict) else {}
    return {
        "wall_seconds": _wall_seconds(doc),
        "hardware_threads": _positive_int(hardware.get("host_logical_cpus") or hardware.get("affinity_cpus")),
        "stages": stages,
    }


def _load_saved_report(data_dir: Path, name: Any) -> dict[str, Any] | None:
    if not isinstance(name, str) or not name or "/" in name or name.startswith("."):
        return None
    candidates = (
        data_dir / _SUITE_DIR / "results" / name,
        data_dir / "etc" / "forge-benchmarks" / "reports" / name,
    )
    for path in candidates:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            return doc
    return None


def _stage_rate(view: dict[str, Any], name: str, width: str) -> float | None:
    stages = view.get("stages") if isinstance(view.get("stages"), dict) else {}
    inner = stages.get("stages") if isinstance(stages.get("stages"), dict) else {}
    stage = inner.get(name) if isinstance(inner.get(name), dict) else {}
    level = stage.get(width) if isinstance(stage.get(width), dict) else {}
    return _positive_float(level.get("rate"))


def _geometric_speedup(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    logs = []
    for candidate, reference in pairs:
        if candidate <= 0 or reference <= 0:
            return None
        logs.append(math.log(candidate / reference))
    return math.exp(sum(logs) / len(logs))


def composite_score(reference: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    """100 on the reference run. Shorter wall time and two-thread throughput weigh more than one thread."""
    names = ("postgres", "duckdb", "sqlite", "compute")
    single_pairs = []
    multi_pairs = []
    for name in names:
        single = _stage_rate(candidate, name, "single")
        single_ref = _stage_rate(reference, name, "single")
        multi = _stage_rate(candidate, name, "double")
        multi_ref = _stage_rate(reference, name, "double")
        if None in (single, single_ref, multi, multi_ref):
            return None
        single_pairs.append((single, single_ref))
        multi_pairs.append((multi, multi_ref))
    ref_stages = reference.get("stages") if isinstance(reference.get("stages"), dict) else {}
    cand_stages = candidate.get("stages") if isinstance(candidate.get("stages"), dict) else {}
    ref_wall = _positive_float(reference.get("wall_seconds") or ref_stages.get("wall_seconds"))
    cand_wall = _positive_float(candidate.get("wall_seconds") or cand_stages.get("wall_seconds"))
    if ref_wall is None or cand_wall is None:
        return None
    single = _geometric_speedup(single_pairs)
    multi = _geometric_speedup(multi_pairs)
    if single is None or multi is None:
        return None
    weighted = (
        COMPOSITE_WEIGHTS["overall_time"] * math.log(ref_wall / cand_wall)
        + COMPOSITE_WEIGHTS["multithread"] * math.log(multi)
        + COMPOSITE_WEIGHTS["singlethread"] * math.log(single)
    )
    return 100.0 * math.exp(weighted)


def stress_score(reference: dict[str, Any] | None, candidate: dict[str, Any] | None) -> float | None:
    if not isinstance(reference, dict) or not isinstance(candidate, dict):
        return None
    names = ("postgres", "duckdb", "sqlite", "compute")
    pairs = []
    for name in names:
        ref_level = reference.get(name) if isinstance(reference.get(name), dict) else {}
        cand_level = candidate.get(name) if isinstance(candidate.get(name), dict) else {}
        ref_rate = _positive_float(ref_level.get("rate"))
        cand_rate = _positive_float(cand_level.get("rate"))
        if ref_rate is None or cand_rate is None:
            return None
        pairs.append((cand_rate, ref_rate))
    ref_wall = _positive_float(reference.get("wall_seconds"))
    cand_wall = _positive_float(candidate.get("wall_seconds"))
    throughput = _geometric_speedup(pairs)
    if throughput is None or ref_wall is None or cand_wall is None:
        return None
    weighted = (
        STRESS_WEIGHTS["overall_time"] * math.log(ref_wall / cand_wall)
        + STRESS_WEIGHTS["oversubscribed"] * math.log(throughput)
    )
    return 100.0 * math.exp(weighted)


def row_from_profile(peer_id: str, label: str, profile_doc: dict[str, Any] | None) -> dict[str, Any]:
    doc = profile_doc if isinstance(profile_doc, dict) else {}
    bench = doc.get("benchmark") if isinstance(doc.get("benchmark"), dict) else {}
    sibling = doc.get("fmsbench") if isinstance(doc.get("fmsbench"), dict) else None
    hardware = doc.get("hardware") if isinstance(doc.get("hardware"), dict) else {}
    fleet = {
        "bench_version": bench.get("bench_version"),
        "fleet_mark": bench.get("fleet_mark"),
        "cpu_single_mark": bench.get("cpu_single_mark"),
        "cpu_multi_mark": bench.get("cpu_multi_mark"),
        "memory_mark": bench.get("memory_mark"),
        "disk_mark": bench.get("disk_mark"),
        "measured_at": doc.get("measured_at"),
    }
    return {
        "peer_id": peer_id,
        "label": label,
        "node_id": hardware.get("node_id") or sibling.get("node") if sibling else hardware.get("node_id"),
        "fleet": fleet,
        "capacity": host_capacity(hardware),
        "fmsbench": sibling or {"suite": SUITE, "status": "not_run"},
    }


def _snapshot_path(data_dir: Path) -> Path:
    return _benchmarks_dir(data_dir) / "mesh-snapshot.json"


def _load_snapshot(data_dir: Path) -> dict[str, Any]:
    path = data_dir / "etc" / "forge-benchmarks" / "mesh-snapshot.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _row_measured(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return False
    fleet = row.get("fleet") if isinstance(row.get("fleet"), dict) else {}
    fms = row.get("fmsbench") if isinstance(row.get("fmsbench"), dict) else {}
    if fleet.get("fleet_mark") is not None:
        return True
    if fms.get("status") in {"passed", "failed", "incomplete", "running"}:
        return True
    return fms.get("stress_status") in {"passed", "failed", "running"}


def _slim_row(row: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(row))
    fms = copied.get("fmsbench")
    if isinstance(fms, dict):
        fms.pop("log_excerpt", None)
    return copied


def _merge_saved_rows(data_dir: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last measured row when a peer cannot be read right now."""
    snapshot = _load_snapshot(data_dir)
    merged: list[dict[str, Any]] = []
    for row in rows:
        peer_id = str(row.get("peer_id") or "")
        if peer_id and _row_measured(row):
            snapshot[peer_id] = {"saved_at": time.time(), "row": _slim_row(row)}
            merged.append(row)
            continue
        saved = snapshot.get(peer_id) if peer_id else None
        saved_row = saved.get("row") if isinstance(saved, dict) else None
        if isinstance(saved_row, dict):
            restored = _slim_row(saved_row)
            restored["from_saved"] = True
            restored["saved_at"] = saved.get("saved_at")
            if row.get("error"):
                restored["live_error"] = row.get("error")
            merged.append(restored)
            continue
        merged.append(row)
    path = _snapshot_path(data_dir)
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return merged


def batch_status(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / "etc" / "forge-benchmarks" / "batch.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def comparison(data_dir: Path, *, fetch_peer: Callable[[str], tuple[int, dict[str, Any] | None]] | None = None) -> dict[str, Any]:
    from fleet_server import host_profile, remote_peers

    def default_fetch(peer_id: str) -> tuple[int, dict[str, Any] | None]:
        code, raw, _ctype = remote_peers.proxy_get(data_dir, peer_id, "/v1/host/profile")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        return code, payload if isinstance(payload, dict) else None

    saved = host_profile.load_profile(data_dir) or {}
    local_doc = {
        "hardware": saved.get("hardware") or host_profile.static_hardware(),
        "benchmark": saved.get("benchmark"),
        "measured_at": saved.get("measured_at"),
        "fmsbench": public_view(data_dir),
    }
    rows = [row_from_profile("local", socket.gethostname(), local_doc)]
    fetcher = fetch_peer or default_fetch
    for peer in remote_peers.list_peers(data_dir).get("peers") or []:
        peer_id = str(peer.get("id") or "")
        label = str(peer.get("label") or peer_id)
        if not peer_id:
            continue
        try:
            code, payload = fetcher(peer_id)
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "peer_id": peer_id,
                "label": label,
                "error": str(exc)[:200],
                "fleet": None,
                "fmsbench": {"suite": SUITE, "status": "unavailable"},
            })
            continue
        if code != 200 or not isinstance(payload, dict):
            rows.append({
                "peer_id": peer_id,
                "label": label,
                "error": "http_%s" % code,
                "fleet": None,
                "fmsbench": {"suite": SUITE, "status": "unavailable"},
            })
            continue
        rows.append(row_from_profile(peer_id, label, payload))
    rows = _merge_saved_rows(data_dir, rows)
    reference = next((row for row in rows if row.get("peer_id") == "local"), None)
    ref_fms = reference.get("fmsbench") if isinstance(reference, dict) else None
    if isinstance(ref_fms, dict) and ref_fms.get("stages"):
        for row in rows:
            fms = row.get("fmsbench")
            if not isinstance(fms, dict) or not fms.get("stages"):
                continue
            scored = composite_score(ref_fms, fms)
            if scored is not None:
                fms["composite_score"] = round(scored, 1)
            stress_scored = stress_score(ref_fms.get("stress"), fms.get("stress"))
            if stress_scored is not None:
                fms["stress_score"] = round(stress_scored, 1)
    return {
        "ok": True,
        "name": "Forge Benchmarks",
        "separation": "hardware and Market Studio are different measurements",
        "reference_peer_id": "local",
        "batch": batch_status(data_dir),
        "composite_weights": dict(COMPOSITE_WEIGHTS),
        "stress_weights": dict(STRESS_WEIGHTS),
        "rows": rows,
    }


def _safe_label(raw: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in (raw or "node"))
    return (cleaned[:48] or "node")


def probe_runtime() -> dict[str, Any]:
    from shutil import which

    if which("docker") is None:
        return {"compose": False, "detail": "Docker Engine is not on PATH."}
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"compose": False, "detail": str(exc)[:240]}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "docker compose version failed").strip()
        return {"compose": False, "detail": detail[:240]}
    return {"compose": True, "detail": (proc.stdout or "").strip()[:240]}


def _running(doc: dict[str, Any] | None, now: float) -> bool:
    if not doc:
        return False
    if doc.get("status") == "running":
        started = float(doc.get("started_at") or 0)
        if (now - started) < _STALE_S:
            return True
    if doc.get("stress_status") == "running":
        started = float(doc.get("stress_started_at") or 0)
        return (now - started) < _STALE_S
    return False


def _finish(data_dir: Path, profile: str, status: str, **extra: Any) -> None:
    current = load_result(data_dir) or {}
    finished = time.time()
    current.update({
        "suite": SUITE,
        "suite_version": SUITE_VERSION,
        "status": status,
        "profile": profile,
        "finished_at": finished,
        "node": _safe_label(socket.gethostname()),
    })
    current.update(extra)
    save_result(data_dir, current)
    _archive_report(data_dir, extra.get("result_name"))
    summary = extra.get("summary") if isinstance(extra.get("summary"), dict) else None
    _append_history(data_dir, "market-studio", {
        "saved_at": finished,
        "profile": profile,
        "status": status,
        "result_name": extra.get("result_name"),
        "error": extra.get("error"),
        "summary": summary,
    })


def materialize_suite(dest: Path) -> None:
    src = bundle_dir()
    if not src.is_dir():
        raise FileNotFoundError("FMSBench bundle is not installed")
    dest.mkdir(parents=True, exist_ok=True)
    for name in _BUNDLE_FILES:
        data = (src / name).read_bytes()
        target = dest / name
        if not target.is_file() or target.read_bytes() != data:
            target.write_bytes(data)
    (dest / "run.sh").chmod(0o755)


def _new_result_file(suite: Path, before: set[str]) -> Path | None:
    folder = suite / "results"
    if not folder.is_dir():
        return None
    fresh = [p for p in folder.glob("fmsbench-*.json") if p.name not in before]
    if not fresh:
        return None
    return max(fresh, key=lambda p: p.stat().st_mtime)


def _update_running(data_dir: Path, profile: str, **fields: Any) -> None:
    current = load_result(data_dir) or {}
    if profile == "stress":
        current["stress_status"] = "running"
        current["heartbeat_at"] = time.time()
        for key in ("phase", "phases", "log_excerpt"):
            if key in fields:
                current[key] = fields[key]
        save_result(data_dir, current)
        return
    current.update({
        "suite": SUITE,
        "suite_version": SUITE_VERSION,
        "status": "running",
        "profile": profile,
        "heartbeat_at": time.time(),
        "node": _safe_label(socket.gethostname()),
    })
    current.update(fields)
    save_result(data_dir, current)


def _stream_run(data_dir: Path, profile: str, proc: subprocess.Popen[bytes], timeout_s: float) -> tuple[str, int]:
    assert proc.stdout is not None
    fd = proc.stdout.fileno()
    os.set_blocking(fd, False)
    raw = bytearray()
    deadline = time.time() + timeout_s
    last_phase = ""
    last_write = 0.0
    while True:
        if time.time() >= deadline:
            proc.kill()
            raw.extend(b"\nThe run exceeded its time limit.\n")
            break
        ready, _, _ = select.select([fd], [], [], 1.0)
        if ready:
            try:
                piece = os.read(fd, 65536)
            except BlockingIOError:
                piece = b""
            if piece == b"":
                break
            raw.extend(piece)
        log = redact_log(raw.decode("utf-8", "replace"))
        phase = current_phase(log)
        now = time.time()
        if phase != last_phase or now - last_write >= 1.0:
            last_phase = phase
            last_write = now
            _update_running(
                data_dir,
                profile,
                phase=phase,
                phases=phases_from_log(log),
                log_excerpt=clip_log(log),
            )
        if proc.poll() is not None and not ready:
            break
    try:
        rest = os.read(fd, 1024 * 1024)
    except (BlockingIOError, OSError):
        rest = b""
    if rest:
        raw.extend(rest)
    code = proc.wait(timeout=15)
    return redact_log(raw.decode("utf-8", "replace")), int(code)


def stress_thread_count() -> int:
    """Twice the hardware threads, capped so one host cannot fork without a bound."""
    threads = os.cpu_count() or 1
    return max(2, min(64, threads * 2))


def _run_command(profile: str) -> list[str]:
    label = _safe_label(socket.gethostname())
    if profile == "stress":
        return [
            "./run.sh",
            "--label",
            label,
            "--profile",
            "standard",
            "--threads",
            "1",
            "--workers",
            str(stress_thread_count()),
            "--repeats",
            "1",
            "--trials",
            "1",
            "--duration",
            "5",
            "--stress-only",
        ]
    return ["./run.sh", "--label", label, "--profile", profile, *_FLAGS[profile]]


def _docker_command(cmd: list[str]) -> list[str]:
    """Use `sg docker` when the service account is in the group but this process is not."""
    try:
        info = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        info = None
    if info is not None and info.returncode == 0 and (info.stdout or "").strip():
        return cmd
    try:
        grouped = subprocess.run(
            ["sg", "docker", "-c", "docker info --format '{{.ServerVersion}}'"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return cmd
    if grouped.returncode != 0 or not (grouped.stdout or "").strip():
        return cmd
    return ["sg", "docker", "-c", " ".join(shlex.quote(part) for part in cmd)]


def _compose_project(suite: Path) -> str:
    digest = hashlib.sha256(str(suite.resolve()).encode()).hexdigest()[:8]
    return "fmsbench-" + digest


def cleanup_runtime(suite: Path, *, run_cmd: Callable[..., tuple[int, str]] | None = None) -> dict[str, Any]:
    """Remove containers, volumes, the runner image, and work files. Keep result JSON."""
    suite.mkdir(parents=True, exist_ok=True)
    project = _compose_project(suite)
    env = {k: v for k, v in os.environ.items() if "TOKEN" not in k and "PASSWORD" not in k and "SECRET" not in k}
    env["FMSBENCH_PROJECT"] = project
    env["FMSBENCH_PASSWORD"] = "cleanup"
    notes: list[str] = []

    def invoke(argv: list[str]) -> tuple[int, str]:
        if run_cmd is not None:
            return run_cmd(argv)
        try:
            proc = subprocess.run(
                argv,
                cwd=suite,
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, str(exc)[:240]
        return proc.returncode, ((proc.stderr or proc.stdout or "").strip())[-400:]

    code, detail = invoke(["docker", "compose", "-p", project, "down", "-v", "--remove-orphans", "--rmi", "local"])
    if code != 0 and detail:
        notes.append(detail)

    work = suite / "work"
    if work.exists():
        try:
            shutil.rmtree(work)
        except OSError:
            wipe_code, wipe_detail = invoke([
                "docker", "run", "--rm",
                "-v", f"{work.resolve()}:/target",
                "--entrypoint", "sh",
                "postgres:17",
                "-c", "rm -rf /target/* /target/.[!.]* /target/..?*",
            ])
            if wipe_code != 0 and wipe_detail:
                notes.append(wipe_detail)
            try:
                shutil.rmtree(work)
            except OSError:
                pass
    for relative in (".env", "results/preflight-last.json"):
        target = suite / relative
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
    cache = suite / "__pycache__"
    if cache.is_dir():
        shutil.rmtree(cache, ignore_errors=True)
    results = suite / "results"
    if results.is_dir():
        for tmp in results.glob("*.tmp"):
            try:
                tmp.unlink()
            except OSError:
                pass
    kept = sorted(p.name for p in results.glob("fmsbench-*.json")) if results.is_dir() else []
    return {"ok": not notes, "project": project, "kept_results": kept, "detail": "; ".join(notes)[:500]}


def execute_run(data_dir: Path, profile: str) -> None:
    suite = data_dir / _SUITE_DIR
    try:
        materialize_suite(suite)
        results = suite / "results"
        before = {p.name for p in results.glob("fmsbench-*.json")} if results.is_dir() else set()
        env = {
            k: v
            for k, v in os.environ.items()
            if "TOKEN" not in k and "PASSWORD" not in k and "SECRET" not in k
        }
        cmd = _docker_command(_run_command(profile))
        _update_running(data_dir, profile, phase="Checking the host", log_excerpt="")
        env["PYTHONUNBUFFERED"] = "1"
        env["COMPOSE_ANSI"] = "never"
        env["BUILDKIT_PROGRESS"] = "plain"
        proc = subprocess.Popen(
            cmd,
            cwd=suite,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log, returncode = _stream_run(data_dir, profile, proc, _TIMEOUT_S[profile])
        _update_running(
            data_dir,
            profile,
            phase="Stopping the benchmark containers",
            log_excerpt=clip_log(log),
        )
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=suite,
            timeout=180,
            capture_output=True,
            text=True,
            check=False,
        )
        phases = phases_from_log(log)
        excerpt = clip_log(log)
        proc = subprocess.CompletedProcess(cmd, returncode, log, "")
        if proc.returncode != 0:
            if profile == "stress":
                _save_stress(data_dir, {}, log_excerpt=excerpt, error="run_failed")
            else:
                _finish(data_dir, profile, "failed", error="run_failed", detail=log[-500:], phases=phases, log_excerpt=excerpt)
            return
        picked = _new_result_file(suite, before)
        if picked is None:
            if profile == "stress":
                _save_stress(data_dir, {}, log_excerpt=excerpt, error="no_result")
            else:
                _finish(data_dir, profile, "failed", error="no_result", phases=phases, log_excerpt=excerpt)
            return
        report = json.loads(picked.read_text(encoding="utf-8"))
        if isinstance(report, dict) and report.get("status") == "stress_only" and isinstance(report.get("stress"), dict):
            _save_stress(data_dir, report["stress"], log_excerpt=excerpt, result_name=picked.name)
            return
        if not isinstance(report, dict) or report.get("status") != "passed" or not report_has_engine_evidence(report):
            _finish(
                data_dir,
                profile,
                "incomplete",
                error="missing_engine_evidence",
                result_name=picked.name if isinstance(report, dict) else None,
                phases=phases,
                log_excerpt=excerpt,
            )
            return
        if not (phases["postgres_sql"] and phases["duckdb_sql"] and phases["sqlite_sql"] and phases["numpy_compute"]):
            _finish(
                data_dir,
                profile,
                "incomplete",
                error="log_missing_engine_phases",
                result_name=picked.name,
                phases=phases,
                log_excerpt=excerpt,
            )
            return
        _finish(
            data_dir,
            profile,
            "passed",
            result_name=picked.name,
            summary=summarize_fms_report(report),
            phases=phases,
            log_excerpt=excerpt,
            error=None,
            detail=None,
        )
    except Exception as exc:  # noqa: BLE001 — persist the failure in the FMSBench file only
        if profile == "stress":
            _save_stress(data_dir, {}, log_excerpt="", error=str(exc)[:240])
        else:
            _finish(data_dir, profile, "failed", error="run_failed", detail=str(exc)[:500])
    finally:
        cleanup_runtime(suite)


def _save_stress(
    data_dir: Path,
    stress: dict[str, Any],
    *,
    log_excerpt: str,
    error: str | None = None,
    result_name: str | None = None,
) -> None:
    current = load_result(data_dir) or {}
    finished = time.time()
    current["suite"] = current.get("suite") or SUITE
    current["suite_version"] = str(current.get("suite_version") or SUITE_VERSION)
    current["stress_finished_at"] = finished
    if error:
        current["stress_status"] = "failed"
        current["stress_error"] = error
    else:
        current["stress"] = stress
        current["stress_status"] = "passed"
        current["stress_error"] = None
    if log_excerpt:
        current["log_excerpt"] = log_excerpt
    if current.get("status") == "running" and current.get("profile") == "stress":
        current["status"] = "not_run"
    save_result(data_dir, current)
    if result_name:
        _archive_report(data_dir, result_name)
    _append_history(data_dir, "market-studio-stress", {
        "saved_at": finished,
        "status": current.get("stress_status"),
        "error": error,
        "result_name": result_name,
        "threads": stress.get("threads") if isinstance(stress, dict) else None,
        "wall_seconds": stress.get("wall_seconds") if isinstance(stress, dict) else None,
    })


def start_run(
    data_dir: Path,
    profile: str,
    *,
    probe: Callable[[], dict[str, Any]] | None = None,
    runner: Callable[[Path, str], None] | None = None,
) -> tuple[dict[str, Any], int]:
    if profile not in _FLAGS:
        return {"ok": False, "error": "unknown_profile"}, 400
    runtime = (probe or probe_runtime)()
    if not runtime.get("compose"):
        if profile == "stress":
            _save_stress(data_dir, {}, log_excerpt="", error="compose_unavailable")
        else:
            _finish(
                data_dir,
                profile,
                "failed",
                error="compose_unavailable",
                detail=runtime.get("detail"),
                started_at=time.time(),
            )
        return {
            "ok": False,
            "error": "compose_unavailable",
            "detail": runtime.get("detail"),
            "fmsbench": public_view(data_dir),
        }, 503
    now = time.time()
    with _lock:
        if _running(load_result(data_dir), now):
            return {"ok": False, "error": "busy", "fmsbench": public_view(data_dir)}, 409
        if profile == "stress":
            current = load_result(data_dir) or {
                "suite": SUITE,
                "suite_version": SUITE_VERSION,
                "status": "not_run",
            }
            current["stress_status"] = "running"
            current["stress_started_at"] = now
            current["stress_error"] = None
            save_result(data_dir, current)
        else:
            save_result(data_dir, {
                "suite": SUITE,
                "suite_version": SUITE_VERSION,
                "status": "running",
                "profile": profile,
                "started_at": now,
                "finished_at": None,
                "node": _safe_label(socket.gethostname()),
                "error": None,
            })
    if runner is not None:
        runner(data_dir, profile)
        return {"ok": True, "status": public_view(data_dir).get("status"), "fmsbench": public_view(data_dir)}, 200
    threading.Thread(target=execute_run, args=(data_dir, profile), daemon=True).start()
    return {"ok": True, "status": "running", "profile": profile, "fmsbench": public_view(data_dir)}, 202


def cleanup_saved_run(data_dir: Path) -> tuple[dict[str, Any], int]:
    if _running(load_result(data_dir), time.time()):
        return {"ok": False, "error": "busy", "fmsbench": public_view(data_dir)}, 409
    report = cleanup_runtime(data_dir / _SUITE_DIR)
    code = 200 if report.get("ok") else 500
    return {"ok": bool(report.get("ok")), **report}, code


def _write_batch(data_dir: Path, doc: dict[str, Any]) -> None:
    path = _benchmarks_dir(data_dir) / "batch.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _launch_peer(data_dir: Path, peer_id: str, suite: str, profile: str) -> dict[str, Any]:
    from fleet_server import host_profile, remote_peers

    if suite == "hardware":
        if peer_id == "local":
            out, _err = host_profile.run_benchmark(data_dir)
            return out if isinstance(out, dict) else {"ok": False, "error": "benchmark_failed"}
        code, raw, _ctype = remote_peers.proxy_json(
            data_dir,
            peer_id,
            "/v1/host/profile/benchmark",
            method="POST",
            body=b"{}",
            timeout_s=900,
        )
    else:
        if peer_id == "local":
            out, code = start_run(data_dir, profile)
            out = dict(out)
            out["ok"] = code in {200, 202}
            return out
        code, raw, _ctype = remote_peers.proxy_json(
            data_dir,
            peer_id,
            "/v1/host/profile/fmsbench",
            method="POST",
            body=json.dumps({"profile": profile}).encode("utf-8"),
            timeout_s=90,
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"ok": False, "error": "bad_response"}
    if not isinstance(payload, dict):
        payload = {"ok": False, "error": "bad_response"}
    payload["ok"] = bool(payload.get("ok")) and code in {200, 202}
    if code not in {200, 202} and not payload.get("error"):
        payload["error"] = "http_%s" % code
    return payload


def start_batch(
    data_dir: Path,
    suite: str,
    *,
    profile: str = "standard",
    launch: Callable[[Path, str, str, str], dict[str, Any]] | None = None,
    spawn: Callable[[Callable[[], None]], None] | None = None,
) -> tuple[dict[str, Any], int]:
    """Start one suite on this host and every configured peer."""
    from fleet_server import remote_peers

    if suite not in {"hardware", "market_studio"}:
        return {"ok": False, "error": "unknown_suite"}, 400
    if suite == "market_studio" and profile not in _FLAGS:
        return {"ok": False, "error": "unknown_profile"}, 400
    current = batch_status(data_dir)
    if isinstance(current, dict) and current.get("status") == "running":
        started = float(current.get("started_at") or 0)
        if time.time() - started < _STALE_S:
            return {"ok": False, "error": "busy", "batch": current}, 409
    targets = [{"peer_id": "local", "label": socket.gethostname(), "status": "queued", "error": None}]
    for peer in remote_peers.list_peers(data_dir).get("peers") or []:
        peer_id = str(peer.get("id") or "")
        if not peer_id:
            continue
        targets.append({
            "peer_id": peer_id,
            "label": str(peer.get("label") or peer_id),
            "status": "queued",
            "error": None,
        })
    doc: dict[str, Any] = {
        "ok": True,
        "status": "running",
        "suite": suite,
        "profile": profile if suite == "market_studio" else None,
        "started_at": time.time(),
        "targets": targets,
    }
    _write_batch(data_dir, doc)
    starter = launch or _launch_peer

    def job() -> None:
        threads: list[threading.Thread] = []

        def one(target: dict[str, Any]) -> None:
            try:
                result = starter(data_dir, str(target["peer_id"]), suite, profile)
                status = "started" if result.get("ok") else "failed"
                error = None if result.get("ok") else str(result.get("error") or "failed")[:200]
            except Exception as exc:  # noqa: BLE001 — one peer must not cancel the others
                status = "failed"
                error = str(exc)[:200]
            with _lock:
                target["status"] = status
                target["error"] = error
                _write_batch(data_dir, doc)

        for target in targets:
            threads.append(threading.Thread(target=one, args=(target,), daemon=True))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        doc["status"] = "finished"
        doc["finished_at"] = time.time()
        _write_batch(data_dir, doc)

    if spawn is not None:
        spawn(job)
    else:
        threading.Thread(target=job, daemon=True).start()
    return doc, 202
