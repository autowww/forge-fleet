"""Host hardware profile + Fleet benchmark persistence."""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any

from fleet_server import fleet_bench, host_stats, telemetry_rollup

_PROFILE = "host-profile.json"
_PROGRESS = "fleet-bench-progress.json"
_BENCH_COOLDOWN = 600.0
_last_bench_at = 0.0


def profile_path(data_dir: Path) -> Path:
    return data_dir / "etc" / _PROFILE


def load_profile(data_dir: Path) -> dict[str, Any] | None:
    p = profile_path(data_dir)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_profile(data_dir: Path, doc: dict[str, Any]) -> None:
    p = profile_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _root_disk() -> dict[str, Any] | None:
    try:
        rows = host_stats.disk_space_snapshot()
    except OSError:
        return None
    root = next((r for r in rows if r.get("mount") == "/"), None)
    if root is None and rows:
        root = rows[0]
    if not root:
        return None
    return {
        "total_gb": root.get("total_gb"),
        "free_gb": root.get("free_gb"),
    }


def static_hardware() -> dict[str, Any]:
    snap = host_stats.snapshot()
    mem = snap.get("memory") if isinstance(snap.get("memory"), dict) else {}
    cpufreq = {k: snap.get(k) for k in ("cpu_freq_max_mhz", "cpu_freq_min_mhz") if snap.get(k)}
    return {
        "node_id": socket.gethostname(),
        "logical_cpus": snap.get("cpus"),
        "physical_cpus": snap.get("cpu_cores_physical"),
        "cpufreq": cpufreq,
        "memory_total_kb": mem.get("total_kb"),
        "memory_available_kb": mem.get("available_kb"),
        "disk": _root_disk(),
        "platform": snap.get("platform"),
        "machine": snap.get("machine"),
    }


def load_history(db_path: Path, period: str) -> dict[str, Any]:
    import sqlite3

    from fleet_server import store

    sec = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}.get(period, 3600)
    since = time.time() - sec
    conn = store.connect(db_path)
    try:
        return telemetry_rollup.load_profile_history(conn, since)
    finally:
        conn.close()


def progress_path(data_dir: Path) -> Path:
    return data_dir / "etc" / _PROGRESS


def write_benchmark_progress(data_dir: Path, doc: dict[str, Any]) -> None:
    path = progress_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) + "\n", encoding="utf-8")


def read_benchmark_progress(data_dir: Path) -> dict[str, Any] | None:
    path = progress_path(data_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    updated = float(doc.get("updated_at") or 0)
    if doc.get("status") == "running" and time.time() - updated > 180:
        doc = dict(doc)
        doc["status"] = "stale"
    return doc


def clear_benchmark_progress(data_dir: Path) -> None:
    try:
        progress_path(data_dir).unlink(missing_ok=True)
    except OSError:
        return


def profile_payload(data_dir: Path, db_path: Path, period: str = "24h") -> dict[str, Any]:
    from fleet_server import fmsbench_runs

    prof = load_profile(data_dir) or {}
    return {
        "ok": True,
        "hardware": static_hardware(),
        "benchmark": prof.get("benchmark"),
        "benchmark_progress": read_benchmark_progress(data_dir),
        "fmsbench": fmsbench_runs.public_view(data_dir),
        "measured_at": prof.get("measured_at"),
        "history": load_history(db_path, period),
        "period": period,
    }


def run_benchmark(data_dir: Path) -> tuple[dict[str, Any], str | None]:
    global _last_bench_at
    now = time.time()
    if now - _last_bench_at < _BENCH_COOLDOWN:
        return {"ok": False, "error": "cooldown", "retry_after_s": int(_BENCH_COOLDOWN - (now - _last_bench_at))}, None
    la = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    cpus = os.cpu_count() or 1
    if la > cpus:
        return {"ok": False, "error": "busy"}, None
    def on_progress(step: str, detail: str) -> None:
        write_benchmark_progress(data_dir, {
            "status": "running",
            "kind": "fleet_mark",
            "step": step,
            "detail": detail,
            "started_at": now,
            "updated_at": time.time(),
        })

    on_progress("cpu_single", "Single-core mix")
    try:
        bench = fleet_bench.run_benchmark(data_dir, on_progress=on_progress)
    except TimeoutError:
        write_benchmark_progress(data_dir, {
            "status": "failed", "kind": "fleet_mark", "step": "cpu_multi",
            "detail": "The all-core mix did not finish in time.",
            "started_at": now, "updated_at": time.time(),
        })
        return {"ok": False, "error": "benchmark_timeout"}, None
    except Exception as exc:  # noqa: BLE001 — return JSON instead of dropping the HTTP connection
        write_benchmark_progress(data_dir, {
            "status": "failed", "kind": "fleet_mark", "step": "cpu_single",
            "detail": str(exc)[:240],
            "started_at": now, "updated_at": time.time(),
        })
        return {"ok": False, "error": "benchmark_failed", "detail": str(exc)[:400]}, None
    from fleet_server import fmsbench_runs

    doc = fmsbench_runs.fleet_profile_document(
        load_profile(data_dir),
        bench,
        static_hardware(),
        now,
    )
    save_profile(data_dir, doc)
    clear_benchmark_progress(data_dir)
    _last_bench_at = now
    return {"ok": True, "benchmark": bench, "measured_at": now}, None


def link_probe_bytes(size: int = 1024 * 1024) -> bytes:
    return b"\0" * size
