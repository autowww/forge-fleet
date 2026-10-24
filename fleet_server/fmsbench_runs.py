"""Market Studio benchmark runs, stored apart from the Fleet mark.

The Fleet mark lives in ``etc/host-profile.json`` under ``benchmark``.
This module writes only ``etc/fmsbench-result.json`` and ``fmsbench-suite/``.
"""

from __future__ import annotations

import json
import os
import select
import shlex
import socket
import subprocess
import threading
import time
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
)
_FLAGS = {
    "micro": ("--threads", "2", "--workers", "2", "--repeats", "1", "--trials", "1", "--duration", "1"),
    "smoke": ("--threads", "2", "--workers", "2", "--repeats", "1", "--trials", "1", "--duration", "1"),
    "standard": ("--threads", "8", "--workers", "8", "--repeats", "3", "--trials", "3", "--duration", "5"),
    "large": ("--threads", "8", "--workers", "8", "--repeats", "3", "--trials", "3", "--duration", "5"),
}
_TIMEOUT_S = {"micro": 600, "smoke": 1200, "standard": 7200, "large": 14400}
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
    }
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
        if "numpy numerical" in low:
            nxt = "NumPy compute"
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
        "fmsbench": sibling or {"suite": SUITE, "status": "not_run"},
    }


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
    return {
        "ok": True,
        "separation": "fleet_mark and fmsbench are different measurements",
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
    if not doc or doc.get("status") != "running":
        return False
    started = float(doc.get("started_at") or 0)
    return (now - started) < _STALE_S


def _finish(data_dir: Path, profile: str, status: str, **extra: Any) -> None:
    current = load_result(data_dir) or {}
    current.update({
        "suite": SUITE,
        "suite_version": SUITE_VERSION,
        "status": status,
        "profile": profile,
        "finished_at": time.time(),
        "node": _safe_label(socket.gethostname()),
    })
    current.update(extra)
    save_result(data_dir, current)


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
        cmd = _docker_command(
            ["./run.sh", "--label", _safe_label(socket.gethostname()), "--profile", profile, *_FLAGS[profile]]
        )
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
            _finish(data_dir, profile, "failed", error="run_failed", detail=log[-500:], phases=phases, log_excerpt=excerpt)
            return
        picked = _new_result_file(suite, before)
        if picked is None:
            _finish(data_dir, profile, "failed", error="no_result", phases=phases, log_excerpt=excerpt)
            return
        report = json.loads(picked.read_text(encoding="utf-8"))
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
        _finish(data_dir, profile, "failed", error="run_failed", detail=str(exc)[:500])


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
