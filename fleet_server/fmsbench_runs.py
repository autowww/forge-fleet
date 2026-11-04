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
    # standard and large take --threads/--workers from host_width("threads") in _run_command.
    "standard": ("--repeats", "3", "--trials", "3", "--duration", "5"),
    "large": ("--repeats", "3", "--trials", "3", "--duration", "5"),
    "stress": ("--stress-only",),
    "host-max-cores": (),
    "host-max-threads": (),
    "full": (),
}
_WIDTH_PROFILES = frozenset({"host-max-cores", "host-max-threads"})
_FULL_STEPS = ("standard", "host-max-cores", "host-max-threads", "stress")
_TIMEOUT_S = {
    "micro": 600,
    "smoke": 1200,
    "standard": 7200,
    "large": 14400,
    "stress": 7200,
    "host-max-cores": 7200,
    "host-max-threads": 7200,
    "full": 21600,
}
# Additive capacity, parts of 100. Throughput at the host's hardware thread count
# versus the reference host. One-thread rates stay visible and are not scored.
# DuckDB and NLP are the analytical and narrative share. PostgreSQL is the system of record.
# Compute and SQLite are smaller. Summing host scores is the cluster, in reference-host units.
COMPOSITE_WEIGHTS = {"postgres": 22, "duckdb": 28, "sqlite": 10, "compute": 12, "nlp": 28}
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
        "width_status": doc.get("width_status"),
        "width_profile": doc.get("width_profile"),
        "full_status": doc.get("full_status"),
    }
    raw_widths = doc.get("widths") if isinstance(doc.get("widths"), dict) else {}
    widths_out: dict[str, Any] = {}
    for name, entry in raw_widths.items():
        if not isinstance(entry, dict):
            continue
        shown = dict(entry)
        width_report = _load_saved_report(data_dir, entry.get("result_name"))
        if width_report is not None:
            shown["stages"] = stage_breakdown(width_report)
            width_wall = _wall_seconds(width_report)
            if width_wall is not None:
                shown["wall_seconds"] = width_wall
        widths_out[name] = {k: v for k, v in shown.items() if v is not None}
    if widths_out:
        view["widths"] = widths_out
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
    "NLP memory",
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
        if "nlp memory" in low:
            nxt = "NLP memory"
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
        "nlp_memory": "NLP memory" in log,
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


def report_has_nlp_evidence(doc: dict[str, Any]) -> bool:
    nlp = doc.get("nlp") if isinstance(doc.get("nlp"), dict) else {}
    if _positive_int(nlp.get("planned_bytes")) != 1024 ** 3:
        return False
    scales = nlp.get("scales") if isinstance(nlp.get("scales"), dict) else {}
    one = scales.get("1") if isinstance(scales.get("1"), dict) else {}
    two = scales.get("2") if isinstance(scales.get("2"), dict) else {}
    return _positive_float(one.get("median_docs_per_second")) is not None and _positive_float(two.get("median_docs_per_second")) is not None


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
        "nlp_docs_per_second": (doc.get("nlp") or {}).get("best_docs_per_second") if isinstance(doc.get("nlp"), dict) else None,
        "nlp_planned_bytes": (doc.get("nlp") or {}).get("planned_bytes") if isinstance(doc.get("nlp"), dict) else None,
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


def _widest_scale(scales: dict[str, Any] | None) -> tuple[int, dict[str, Any]] | None:
    """Largest measured worker or thread count, and the raw scale record."""
    if not isinstance(scales, dict):
        return None
    best: tuple[int, dict[str, Any]] | None = None
    for key, raw in scales.items():
        width = _positive_int(key)
        if width is None or not isinstance(raw, dict):
            continue
        if best is None or width > best[0]:
            best = (width, raw)
    return best


def _mark_threads(level: dict[str, float] | None, threads: int | None) -> dict[str, float] | None:
    if level is None or threads is None:
        return level
    level["threads"] = threads
    return level


def _displayed_seconds(single: dict[str, Any] | None, multi: dict[str, Any] | None) -> float:
    """Sum one-thread time and the hardware-width time. Width 1 is one measurement."""
    total = 0.0
    if isinstance(single, dict) and isinstance(single.get("seconds"), (int, float)):
        total += float(single["seconds"])
    multi_threads = _positive_int(multi.get("threads")) if isinstance(multi, dict) else None
    same_as_single = multi_threads == 1 and isinstance(single, dict)
    if isinstance(multi, dict) and not same_as_single and isinstance(multi.get("seconds"), (int, float)):
        total += float(multi["seconds"])
    return total


def stage_breakdown(doc: dict[str, Any]) -> dict[str, Any] | None:
    engines = doc.get("engines") if isinstance(doc.get("engines"), dict) else {}
    compute = doc.get("compute") if isinstance(doc.get("compute"), dict) else {}
    stages: dict[str, Any] = {}
    for name in ("postgres", "duckdb", "sqlite"):
        eng = engines.get(name) if isinstance(engines.get(name), dict) else {}
        scales = (eng.get("concurrency") or {}).get("scales") if isinstance(eng.get("concurrency"), dict) else {}
        single = _level(scales.get("1") if isinstance(scales, dict) else None, "median_jobs_per_second")
        double = _level(scales.get("2") if isinstance(scales, dict) else None, "median_jobs_per_second")
        widest = _widest_scale(scales if isinstance(scales, dict) else None)
        multi = _mark_threads(
            _level(widest[1], "median_jobs_per_second") if widest else None,
            widest[0] if widest else None,
        )
        if single is None and double is None and multi is None:
            continue
        prep = _positive_float(eng.get("prep_seconds"))
        stage_seconds = _displayed_seconds(single, multi)
        if prep is not None:
            stage_seconds += prep
        stages[name] = {
            "prep_seconds": prep,
            "single": single,
            "double": double,
            "multi": multi,
            "stage_seconds": stage_seconds if stage_seconds > 0 else None,
        }
    scales = compute.get("scales") if isinstance(compute.get("scales"), dict) else {}
    loops = _positive_int(compute.get("loops")) or 4
    size = _positive_int(compute.get("size")) or 200_000
    single_c = _level(scales.get("1"), "median_rows_per_second")
    double_c = _level(scales.get("2"), "median_rows_per_second")
    widest_c = _widest_scale(scales)
    multi_c = _mark_threads(
        _level(widest_c[1], "median_rows_per_second") if widest_c else None,
        widest_c[0] if widest_c else None,
    )
    if single_c is not None or double_c is not None or multi_c is not None:
        for workers, level in ((1, single_c), (2, double_c), (widest_c[0] if widest_c else None, multi_c)):
            if isinstance(workers, int) and isinstance(level, dict) and "seconds" not in level:
                derived = _compute_seconds(workers, level["rate"], loops, size)
                if derived is not None:
                    level["seconds"] = derived
        stage_seconds = _displayed_seconds(single_c, multi_c)
        stages["compute"] = {
            "single": single_c,
            "double": double_c,
            "multi": multi_c,
            "stage_seconds": stage_seconds if stage_seconds > 0 else None,
        }
    nlp = doc.get("nlp") if isinstance(doc.get("nlp"), dict) else {}
    nlp_scales = nlp.get("scales") if isinstance(nlp.get("scales"), dict) else {}
    single_n = _level(nlp_scales.get("1"), "median_docs_per_second")
    double_n = _level(nlp_scales.get("2"), "median_docs_per_second")
    widest_n = _widest_scale(nlp_scales)
    multi_n = _mark_threads(
        _level(widest_n[1], "median_docs_per_second") if widest_n else None,
        widest_n[0] if widest_n else None,
    )
    if single_n is not None or double_n is not None or multi_n is not None:
        for key, level in (("1", single_n), ("2", double_n), (str(widest_n[0]) if widest_n else "", multi_n)):
            raw = nlp_scales.get(key) if isinstance(nlp_scales.get(key), dict) else {}
            gib = _positive_float(raw.get("median_gib_per_second"))
            if isinstance(level, dict) and gib is not None:
                level["gib_per_second"] = gib
        stage_seconds = _displayed_seconds(single_n, multi_n)
        stages["nlp"] = {
            "single": single_n,
            "double": double_n,
            "multi": multi_n,
            "stage_seconds": stage_seconds if stage_seconds > 0 else None,
            "planned_bytes": _positive_int(nlp.get("planned_bytes")),
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


def _composite_rate(view: dict[str, Any], name: str) -> float | None:
    """Hardware-width throughput. Older rows that only stored two threads still score."""
    rate = _stage_rate(view, name, "multi")
    if rate is not None:
        return rate
    return _stage_rate(view, name, "double")


def _geometric_speedup(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    logs = []
    for candidate, reference in pairs:
        if candidate <= 0 or reference <= 0:
            return None
        logs.append(math.log(candidate / reference))
    return math.exp(sum(logs) / len(logs))


def composite_parts(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any] | None:
    """100 on the reference. Each stage contributes its weight times the hardware-thread rate ratio.

    The rate is the widest measured scale (the host's logical CPUs, capped at 64).
    One-thread rates stay on the stage grid and do not enter the score, so a fast
    narrow CPU and a slower wide CPU separate on aggregate throughput.

    NLP is included only when both sides measured it. Otherwise the other weights are
    renormalized to 100 and ``nlp_included`` is false, so that partial must not be added
    to a complete cluster total.
    """
    used: list[tuple[int, float]] = []
    nlp_included = False
    for name, weight in COMPOSITE_WEIGHTS.items():
        cand = _composite_rate(candidate, name)
        ref = _composite_rate(reference, name)
        if cand is None or ref is None:
            if name == "nlp":
                continue
            return None
        if name == "nlp":
            nlp_included = True
        used.append((int(weight), cand / ref))
    weight_sum = sum(weight for weight, _ratio in used)
    if weight_sum <= 0:
        return None
    score = 100.0 * sum(weight * ratio for weight, ratio in used) / weight_sum
    return {"score": score, "nlp_included": nlp_included}


def composite_score(reference: dict[str, Any], candidate: dict[str, Any]) -> float | None:
    parts = composite_parts(reference, candidate)
    if parts is None:
        return None
    return float(parts["score"])


def cluster_total(parts: list[tuple[float, bool]], *, reference_nlp: bool) -> float:
    """Sum reference-equivalents. Once the reference has NLP, skip hosts that do not."""
    chosen = [score for score, nlp in parts if nlp or not reference_nlp]
    return float(sum(chosen))


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


def _width_score_view(fms: dict[str, Any], name: str) -> dict[str, Any] | None:
    widths = fms.get("widths") if isinstance(fms.get("widths"), dict) else {}
    entry = widths.get(name) if isinstance(widths.get(name), dict) else None
    if not isinstance(entry, dict) or not isinstance(entry.get("stages"), dict):
        return None
    if not entry.get("wall_seconds"):
        return None
    return {"wall_seconds": entry.get("wall_seconds"), "stages": entry.get("stages")}


def batch_status(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / "etc" / "forge-benchmarks" / "batch.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


_BENCH_PEER_TIMEOUT_S = 8.0
_COMPARISON_CACHE_S = 15.0
_comparison_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_comparison_cache_lock = threading.Lock()


def _cached_comparison(data_dir: Path) -> dict[str, Any] | None:
    key = str(data_dir.resolve())
    now = time.time()
    with _comparison_cache_lock:
        hit = _comparison_cache.get(key)
        if hit is None or (now - hit[0]) >= _COMPARISON_CACHE_S:
            return None
        return json.loads(json.dumps(hit[1]))


def _store_comparison(data_dir: Path, doc: dict[str, Any]) -> None:
    with _comparison_cache_lock:
        _comparison_cache[str(data_dir.resolve())] = (time.time(), doc)


def _peer_row_from_fetch(peer_id: str, label: str, code: int, payload: dict[str, Any] | None) -> dict[str, Any]:
    if code != 200 or not isinstance(payload, dict):
        return {
            "peer_id": peer_id,
            "label": label,
            "error": "http_%s" % code,
            "fleet": None,
            "fmsbench": {"suite": SUITE, "status": "unavailable"},
        }
    return row_from_profile(peer_id, label, payload)


def _fetch_remote_rows(
    peers: list[dict[str, Any]],
    fetcher: Callable[[str], tuple[int, dict[str, Any] | None]],
) -> list[dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor

    usable = [peer for peer in peers if str(peer.get("id") or "")]

    def one(peer: dict[str, Any]) -> dict[str, Any]:
        peer_id = str(peer.get("id") or "")
        label = str(peer.get("label") or peer_id)
        try:
            code, payload = fetcher(peer_id)
        except Exception as exc:  # noqa: BLE001 — one peer must not block the page
            return {
                "peer_id": peer_id,
                "label": label,
                "error": str(exc)[:200],
                "fleet": None,
                "fmsbench": {"suite": SUITE, "status": "unavailable"},
            }
        return _peer_row_from_fetch(peer_id, label, code, payload)

    if len(usable) <= 1:
        return [one(peer) for peer in usable]
    with ThreadPoolExecutor(max_workers=min(8, len(usable))) as pool:
        return list(pool.map(one, usable))


def comparison(data_dir: Path, *, fetch_peer: Callable[[str], tuple[int, dict[str, Any] | None]] | None = None) -> dict[str, Any]:
    from fleet_server import host_profile, remote_peers

    if fetch_peer is None:
        cached = _cached_comparison(data_dir)
        if cached is not None:
            return cached

    def default_fetch(peer_id: str) -> tuple[int, dict[str, Any] | None]:
        code, raw, _ctype = remote_peers.proxy_get(
            data_dir,
            peer_id,
            "/v1/host/profile",
            timeout_s=_BENCH_PEER_TIMEOUT_S,
        )
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
    listed = [peer for peer in (remote_peers.list_peers(data_dir).get("peers") or []) if isinstance(peer, dict)]
    rows.extend(_fetch_remote_rows(listed, fetcher))
    rows = _merge_saved_rows(data_dir, rows)
    reference = next((row for row in rows if row.get("peer_id") == "local"), None)
    ref_fms = reference.get("fmsbench") if isinstance(reference, dict) else None
    capacity_parts: list[tuple[float, bool]] = []
    reference_nlp = False
    if isinstance(ref_fms, dict) and ref_fms.get("stages"):
        reference_parts = composite_parts(ref_fms, ref_fms)
        reference_nlp = bool(reference_parts and reference_parts.get("nlp_included"))
        for row in rows:
            fms = row.get("fmsbench")
            if not isinstance(fms, dict) or not fms.get("stages"):
                continue
            parts = composite_parts(ref_fms, fms)
            if parts is not None:
                fms["composite_score"] = round(float(parts["score"]), 1)
                fms["composite_nlp"] = bool(parts["nlp_included"])
                capacity_parts.append((float(parts["score"]), bool(parts["nlp_included"])))
            stress_scored = stress_score(ref_fms.get("stress"), fms.get("stress"))
            if stress_scored is not None:
                fms["stress_score"] = round(stress_scored, 1)
    if isinstance(ref_fms, dict):
        for row in rows:
            fms = row.get("fmsbench")
            if not isinstance(fms, dict):
                continue
            for name, field in (("host-max-cores", "cores_score"), ("host-max-threads", "threads_score")):
                reference_width = _width_score_view(ref_fms, name)
                candidate_width = _width_score_view(fms, name)
                if reference_width is None or candidate_width is None:
                    continue
                width_scored = composite_score(reference_width, candidate_width)
                if width_scored is not None:
                    fms[field] = round(width_scored, 1)
    doc = {
        "ok": True,
        "name": "Forge Benchmarks",
        "separation": "hardware and Market Studio are different measurements",
        "reference_peer_id": "local",
        "batch": batch_status(data_dir),
        "composite_weights": dict(COMPOSITE_WEIGHTS),
        "composite_model": "additive_host_threads",
        "reference_nlp": reference_nlp,
        "cluster_score": round(cluster_total(capacity_parts, reference_nlp=reference_nlp), 1) if capacity_parts else None,
        "stress_weights": dict(STRESS_WEIGHTS),
        "perf_scoring_version": "1.0",
        "rows": rows,
    }
    if fetch_peer is None:
        _store_comparison(data_dir, doc)
    return doc


_FMS_STAGE_TO_DOMAIN = {
    "postgres": "postgresql",
    "duckdb": "duckdb",
    "sqlite": "sqlite",
    "compute": "numpy",
    "nlp": "nlp",
}


def _fixture_id_from_fms(fms: dict[str, Any]) -> str | None:
    summary = fms.get("summary") if isinstance(fms.get("summary"), dict) else {}
    checksum = summary.get("workload_checksum")
    revision = summary.get("data_revision")
    if checksum and revision:
        return f"{checksum}:{revision}"
    if checksum:
        return str(checksum)
    return None


def _rates_from_fms_stages(fms: dict[str, Any]) -> dict[str, Any]:
    from fleet_server.perf_scoring import StageRates

    inner = {}
    stages_root = fms.get("stages") if isinstance(fms.get("stages"), dict) else {}
    raw = stages_root.get("stages") if isinstance(stages_root.get("stages"), dict) else {}
    out: dict[str, StageRates] = {}
    for fms_key, domain_key in _FMS_STAGE_TO_DOMAIN.items():
        stage = raw.get(fms_key) if isinstance(raw.get(fms_key), dict) else {}
        single = stage.get("single") if isinstance(stage.get("single"), dict) else {}
        multi = stage.get("multi") if isinstance(stage.get("multi"), dict) else {}
        if not multi.get("rate") and isinstance(stage.get("double"), dict):
            multi = stage["double"]
        s_rate = multi.get("rate") if isinstance(multi, dict) else None
        o_rate = single.get("rate") if isinstance(single, dict) else None
        if o_rate is None and s_rate is None:
            continue
        try:
            single_f = float(o_rate or 0)
            max_f = float(s_rate or 0)
        except (TypeError, ValueError):
            continue
        mw = multi.get("threads") if isinstance(multi, dict) else None
        try:
            max_workers = int(mw) if mw is not None else None
        except (TypeError, ValueError):
            max_workers = None
        if max_f <= 0 or single_f <= 0:
            continue
        out[domain_key] = StageRates(single=single_f, max_rate=max_f, max_workers=max_workers)
    return out


def evidence_from_rows(rows: list[dict[str, Any]]) -> list[Any]:
    """Map mesh comparison rows to performance scoring node evidence."""
    from fleet_server.perf_scoring import NodeEvidence

    nodes: list[NodeEvidence] = []
    for row in rows:
        peer_id = str(row.get("peer_id") or "")
        fms = row.get("fmsbench") if isinstance(row.get("fmsbench"), dict) else {}
        cap = row.get("capacity") if isinstance(row.get("capacity"), dict) else {}
        fleet = row.get("fleet") if isinstance(row.get("fleet"), dict) else {}
        label = str(row.get("label") or peer_id)
        if row.get("node_id"):
            label = f"{label} ({row.get('node_id')})"

        evidence = "not_run"
        if row.get("from_saved"):
            evidence = "saved_snapshot"
        elif fms.get("status") == "passed" and fms.get("stages"):
            evidence = "recorded"
        elif fms.get("status") in {"failed", "incomplete"}:
            evidence = "run_failed"
        elif row.get("error") or fms.get("status") == "unavailable":
            evidence = "unavailable"

        profile = str(fms.get("profile") or "standard")
        if profile not in {"", "standard"} and evidence == "recorded":
            pass
        if profile in {"smoke", "micro"}:
            evidence = "incompatible"

        stages = _rates_from_fms_stages(fms)
        connectivity = None
        if row.get("live_error"):
            connectivity = str(row["live_error"])
        elif row.get("error"):
            connectivity = str(row["error"])

        nodes.append(
            NodeEvidence(
                node_id=peer_id or "unknown",
                label=label,
                evidence=evidence,
                stages=stages,
                connectivity=connectivity,
                profile=profile if profile else "standard",
                fixture_id=_fixture_id_from_fms(fms),
                physical_cores=_positive_int(cap.get("physical_cores")),
                logical_cpus=_positive_int(cap.get("hardware_threads")),
                hardware_score=_positive_float(fleet.get("fleet_mark")),
                run_id=str(fms.get("result_name") or "") or None,
            )
        )
    return nodes


def _parse_weight_query(raw: str | None) -> dict[str, float] | None:
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 5:
        return None
    keys = ("postgresql", "duckdb", "sqlite", "numpy", "nlp")
    try:
        return {keys[i]: float(parts[i]) for i in range(5)}
    except ValueError:
        return None


def _market_studio_history(data_dir: Path, limit: int = 40) -> list[dict[str, Any]]:
    path = _benchmarks_dir(data_dir) / "market-studio.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            out.append(doc)
    return out


def performance_score_view(
    data_dir: Path,
    *,
    baseline_peer_id: str | None = None,
    include_snapshots: bool = False,
    weight_csv: str | None = None,
    fetch_peer: Callable[[str], tuple[int, dict[str, Any] | None]] | None = None,
) -> dict[str, Any]:
    from fleet_server.perf_scoring import ScoringPolicy, compute_score

    comp = comparison(data_dir, fetch_peer=fetch_peer)
    rows = comp.get("rows") if isinstance(comp.get("rows"), list) else []
    nodes = evidence_from_rows(rows)
    baseline = (baseline_peer_id or comp.get("reference_peer_id") or "local").strip()
    weights = _parse_weight_query(weight_csv)
    baseline_node = next((n for n in nodes if n.node_id == baseline), None)
    fixture_id = baseline_node.fixture_id if baseline_node else None
    policy = ScoringPolicy(
        baseline_node_id=baseline,
        weights=weights,
        include_snapshots=include_snapshots,
        baseline_fixture_id=fixture_id,
        baseline_profile="standard",
    )
    score = compute_score(nodes, policy)
    from fleet_server.perf_insights import evaluate_insights, evaluate_insights_prioritized

    score["insights_all"] = evaluate_insights(score)
    score["insights"] = evaluate_insights_prioritized(score, limit=6)
    score["legacy_comparison"] = {
        "reference_peer_id": comp.get("reference_peer_id"),
        "cluster_score": comp.get("cluster_score"),
        "composite_model": comp.get("composite_model"),
        "reference_nlp": comp.get("reference_nlp"),
    }
    score["rows"] = rows
    score["batch"] = comp.get("batch")
    score["evidence"] = [
        {
            "peer_id": row.get("peer_id"),
            "label": row.get("label"),
            "from_saved": bool(row.get("from_saved")),
            "saved_at": row.get("saved_at"),
            "live_error": row.get("live_error") or row.get("error"),
            "fmsbench": {
                "status": (row.get("fmsbench") or {}).get("status"),
                "profile": (row.get("fmsbench") or {}).get("profile"),
                "result_name": (row.get("fmsbench") or {}).get("result_name"),
                "finished_at": (row.get("fmsbench") or {}).get("finished_at"),
            },
        }
        for row in rows
    ]
    score["history"] = {"market_studio_local": _market_studio_history(data_dir)}
    return score


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
        if (now - started) < _STALE_S:
            return True
    if doc.get("width_status") == "running":
        started = float(doc.get("width_started_at") or 0)
        if (now - started) < _STALE_S:
            return True
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
    if profile == "stress" or profile in _WIDTH_PROFILES:
        if profile == "stress":
            current["stress_status"] = "running"
        else:
            current["width_status"] = "running"
            current["width_profile"] = profile
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
    return max(2, min(64, host_width("threads") * 2))


def host_width(kind: str) -> int:
    """Physical cores, or hardware threads, bounded to the suite's thread cap."""
    from fleet_server import host_profile

    hw = host_profile.static_hardware()
    logical = _positive_int(hw.get("logical_cpus")) or os.cpu_count() or 1
    physical = _positive_int(hw.get("physical_cpus")) or logical
    width = physical if kind == "cores" else logical
    return max(1, min(64, width))


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
    if profile in _WIDTH_PROFILES or profile in ("standard", "large"):
        kind = "cores" if profile == "host-max-cores" else "threads"
        width = str(host_width(kind))
        dataset = "standard" if profile in _WIDTH_PROFILES else profile
        return [
            "./run.sh",
            "--label",
            label,
            "--profile",
            dataset,
            "--threads",
            width,
            "--workers",
            width,
            "--repeats",
            "3",
            "--trials",
            "3",
            "--duration",
            "5",
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


def _run_once(data_dir: Path, suite: Path, profile: str, env: dict[str, str]) -> dict[str, Any]:
    results = suite / "results"
    before = {p.name for p in results.glob("fmsbench-*.json")} if results.is_dir() else set()
    cmd = _docker_command(_run_command(profile))
    proc = subprocess.Popen(
        cmd,
        cwd=suite,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log, returncode = _stream_run(data_dir, profile, proc, _TIMEOUT_S.get(profile, 7200))
    phases = phases_from_log(log)
    excerpt = clip_log(log)
    if returncode != 0:
        return {"error": "run_failed", "excerpt": excerpt, "phases": phases, "detail": log[-500:]}
    picked = _new_result_file(suite, before)
    if picked is None:
        return {"error": "no_result", "excerpt": excerpt, "phases": phases}
    try:
        report = json.loads(picked.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "bad_json", "excerpt": excerpt, "phases": phases}
    if not isinstance(report, dict):
        return {"error": "bad_json", "excerpt": excerpt, "phases": phases}
    return {
        "error": None,
        "excerpt": excerpt,
        "phases": phases,
        "report": report,
        "result_name": picked.name,
    }


def _save_width(
    data_dir: Path,
    profile: str,
    report: dict[str, Any] | None,
    *,
    log_excerpt: str,
    error: str | None = None,
    result_name: str | None = None,
) -> None:
    current = load_result(data_dir) or {}
    finished = time.time()
    widths = current.get("widths") if isinstance(current.get("widths"), dict) else {}
    entry: dict[str, Any] = {
        "status": "failed" if error else "passed",
        "finished_at": finished,
        "error": error,
        "result_name": result_name,
    }
    if isinstance(report, dict):
        config = report.get("config") if isinstance(report.get("config"), dict) else {}
        entry["threads"] = config.get("threads")
        entry["workers"] = config.get("workers")
        entry["wall_seconds"] = _wall_seconds(report)
        entry["summary"] = summarize_fms_report(report)
    widths[profile] = entry
    current["suite"] = current.get("suite") or SUITE
    current["suite_version"] = str(current.get("suite_version") or SUITE_VERSION)
    current["widths"] = widths
    current["width_status"] = "failed" if error else "passed"
    current["width_profile"] = profile
    current["width_error"] = error
    if log_excerpt:
        current["log_excerpt"] = log_excerpt
    if current.get("status") == "running" and current.get("profile") == profile:
        current["status"] = "not_run"
    save_result(data_dir, current)
    if result_name:
        _archive_report(data_dir, result_name)
    _append_history(data_dir, "market-studio-width", {
        "saved_at": finished,
        "profile": profile,
        "status": entry["status"],
        "threads": entry.get("threads"),
        "workers": entry.get("workers"),
        "result_name": result_name,
        "error": error,
    })


def _record_step(data_dir: Path, profile: str, outcome: dict[str, Any]) -> bool:
    excerpt = str(outcome.get("excerpt") or "")
    phases = outcome.get("phases") if isinstance(outcome.get("phases"), dict) else {}
    error = outcome.get("error")
    report = outcome.get("report") if isinstance(outcome.get("report"), dict) else None
    result_name = outcome.get("result_name") if isinstance(outcome.get("result_name"), str) else None
    if error:
        if profile == "stress":
            _save_stress(data_dir, {}, log_excerpt=excerpt, error=error)
        elif profile in _WIDTH_PROFILES:
            _save_width(data_dir, profile, None, log_excerpt=excerpt, error=error)
        else:
            _finish(
                data_dir,
                profile,
                "failed",
                error=error,
                detail=outcome.get("detail"),
                phases=phases,
                log_excerpt=excerpt,
            )
        return False
    if report is not None and report.get("status") == "stress_only" and isinstance(report.get("stress"), dict):
        _save_stress(data_dir, report["stress"], log_excerpt=excerpt, result_name=result_name)
        return True
    evidence = bool(report) and report.get("status") == "passed" and report_has_engine_evidence(report) and report_has_nlp_evidence(report)
    phases_ok = bool(
        phases.get("postgres_sql") and phases.get("duckdb_sql") and phases.get("sqlite_sql")
        and phases.get("numpy_compute") and phases.get("nlp_memory")
    )
    if not evidence or not phases_ok:
        reason = "missing_engine_evidence" if not evidence else "log_missing_engine_phases"
        if profile in _WIDTH_PROFILES:
            _save_width(data_dir, profile, report, log_excerpt=excerpt, error=reason, result_name=result_name)
        else:
            _finish(
                data_dir,
                profile,
                "incomplete",
                error=reason,
                result_name=result_name,
                phases=phases,
                log_excerpt=excerpt,
            )
        return False
    if profile in _WIDTH_PROFILES:
        _save_width(data_dir, profile, report, log_excerpt=excerpt, result_name=result_name)
        return True
    _finish(
        data_dir,
        profile,
        "passed",
        result_name=result_name,
        summary=summarize_fms_report(report or {}),
        phases=phases,
        log_excerpt=excerpt,
        error=None,
        detail=None,
    )
    return True


def _mark_full(data_dir: Path, status: str, error: str | None = None) -> None:
    current = load_result(data_dir) or {}
    current["full_status"] = status
    current["full_error"] = error
    current["full_finished_at"] = time.time()
    if current.get("status") == "running" and current.get("profile") == "full":
        current["status"] = "passed" if current.get("summary") else "not_run"
        if current.get("summary"):
            current["profile"] = "standard"
    save_result(data_dir, current)


def execute_run(data_dir: Path, profile: str) -> None:
    suite = data_dir / _SUITE_DIR
    steps = _FULL_STEPS if profile == "full" else (profile,)
    failed: list[str] = []
    try:
        materialize_suite(suite)
        env = {
            k: v
            for k, v in os.environ.items()
            if "TOKEN" not in k and "PASSWORD" not in k and "SECRET" not in k
        }
        env["PYTHONUNBUFFERED"] = "1"
        env["COMPOSE_ANSI"] = "never"
        env["BUILDKIT_PROGRESS"] = "plain"
        for step in steps:
            label = {
                "standard": "Standard capacity run",
                "host-max-cores": "Host max cores",
                "host-max-threads": "Host max threads",
                "stress": "Stress at 2× threads",
            }.get(step, "Checking the host")
            _update_running(data_dir, step if profile == "full" else profile, phase=label, log_excerpt="")
            outcome = _run_once(data_dir, suite, step, env)
            if not _record_step(data_dir, step, outcome):
                failed.append(step)
                if profile != "full":
                    return
        if profile == "full":
            _mark_full(data_dir, "failed" if failed else "passed", ",".join(failed) or None)
    except Exception as exc:  # noqa: BLE001 — persist the failure in the FMSBench file only
        detail = str(exc)[:240]
        if profile == "stress":
            _save_stress(data_dir, {}, log_excerpt="", error=detail)
        elif profile in _WIDTH_PROFILES:
            _save_width(data_dir, profile, None, log_excerpt="", error=detail)
        elif profile == "full":
            _mark_full(data_dir, "failed", detail)
        else:
            _finish(data_dir, profile, "failed", error="run_failed", detail=detail)
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
        elif profile == "full":
            _mark_full(data_dir, "failed", "compose_unavailable")
        elif profile in _WIDTH_PROFILES:
            _save_width(data_dir, profile, None, log_excerpt="", error="compose_unavailable")
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
        elif profile in _WIDTH_PROFILES or profile == "full":
            current = load_result(data_dir) or {
                "suite": SUITE,
                "suite_version": SUITE_VERSION,
                "status": "not_run",
            }
            if profile == "full":
                current["status"] = "running"
                current["profile"] = "full"
                current["full_status"] = "running"
                current["full_error"] = None
                current["started_at"] = now
            else:
                current["width_status"] = "running"
                current["width_profile"] = profile
                current["width_started_at"] = now
                current["width_error"] = None
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
