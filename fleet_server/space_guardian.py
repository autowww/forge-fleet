"""Space Guardian — scheduled and pressure-triggered disk self-healing."""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fleet_server import cleanup as fleet_cleanup, lifecycle, space_policy, store
from fleet_server import upgrade_coordinator
from fleet_server.rollout_slot import SLOTS_DIR


_RUN_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_LAST_RUN: dict[str, Any] | None = None
_NEXT_RUN_EPOCH: float | None = None
_THREAD: threading.Thread | None = None


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def space_dir(data_dir: Path) -> Path:
    return data_dir / "space"


def runs_log_path(data_dir: Path) -> Path:
    return space_dir(data_dir) / "runs.jsonl"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_run_log(data_dir: Path, record: dict[str, Any]) -> None:
    path = runs_log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _prune_telemetry(db_path: Path) -> dict[str, Any]:
    conn = store.connect(db_path)
    try:
        before = store.telemetry_time_bounds(conn)
        store._telemetry_prune(conn)  # noqa: SLF001 — shared retention helper
        conn.commit()
        after = store.telemetry_time_bounds(conn)
    finally:
        conn.close()
    removed = max(0, int(before[2] or 0) - int(after[2] or 0))
    return {"ok": True, "rows_removed": removed, "before_count": before[2], "after_count": after[2]}


def _any_rollout_slot_held(db_path: Path) -> bool:
    if not SLOTS_DIR.is_dir():
        return False
    from fleet_server.rollout_slot import _holder_still_active, _read_slot_file  # noqa: SLF001

    for path in SLOTS_DIR.glob("*.json"):
        doc = _read_slot_file(path.stem)
        if not doc:
            continue
        sid = str(doc.get("service_id") or path.stem)
        if _holder_still_active(sid, doc, db_path=db_path):
            return True
    return False


def tier1_enabled() -> bool:
    """Tier 1 targets require cleanup.py extensions."""
    from fleet_server import cleanup as fleet_cleanup

    return bool(getattr(fleet_cleanup, "run_tier1_targets", False))


def approve_volume(data_dir: Path, volume_name: str) -> dict[str, Any]:
    from fleet_server import volume_quarantine

    return volume_quarantine.approve_volume(data_dir, volume_name)


def upgrade_active() -> bool:
    st = upgrade_coordinator.read_status()
    phase = str(st.get("phase") or "idle").strip().lower()
    return phase not in {"", "idle", "complete", "done"}


def should_skip_run(db_path: Path) -> str | None:
    if not space_policy.guardian_enabled():
        return "guardian_disabled"
    if lifecycle.is_draining():
        return "fleet_draining"
    if upgrade_active():
        return "upgrade_active"
    if _any_rollout_slot_held(db_path):
        return "rollout_in_progress"
    return None


def detect_pressure(data_dir: Path) -> dict[str, Any]:
    from fleet_server import host_stats

    mounts = host_stats.disk_space_snapshot()
    pct_thresh = space_policy.pressure_free_pct()
    gb_thresh = space_policy.pressure_free_gb()
    docker_root = Path(str(os.environ.get("FLEET_DOCKER_ROOT") or "/var/lib/docker")).resolve()
    fleet_data = data_dir.resolve()
    watch_mounts: list[str] = []
    for mnt in {str(docker_root), str(fleet_data), "/"}:
        p = Path(mnt)
        while not p.is_dir() and p != p.parent:
            p = p.parent
        if p.is_dir():
            watch_mounts.append(str(p))
    seen: set[str] = set()
    triggered = False
    rows: list[dict[str, Any]] = []
    for row in mounts:
        mnt = str(row.get("mount") or "")
        if mnt in seen:
            continue
        seen.add(mnt)
        relevant = any(mnt == w or w.startswith(mnt + "/") or mnt.startswith(w + "/") for w in watch_mounts)
        free_gb = float(row.get("free_gb") or 0)
        used_pct = float(row.get("used_pct") or 0)
        free_pct = round(100.0 - used_pct, 1)
        under_pressure = relevant and (free_pct < pct_thresh or free_gb < gb_thresh)
        if under_pressure:
            triggered = True
        rows.append(
            {
                **row,
                "free_pct": free_pct,
                "relevant": relevant,
                "under_pressure": under_pressure,
            }
        )
    return {
        "ok": True,
        "under_pressure": triggered,
        "thresholds": {"free_pct_min": pct_thresh, "free_gb_min": gb_thresh},
        "mounts": rows,
    }


def run_tier(
    data_dir: Path,
    db_path: Path,
    tier: int,
    *,
    dry_run: bool = False,
    trigger: str = "manual",
) -> dict[str, Any]:
    skip = should_skip_run(db_path)
    if skip and not dry_run and trigger != "startup":
        return {"ok": True, "skipped": True, "reason": skip, "tier": tier, "trigger": trigger}

    targets: dict[str, Any] = {}
    if tier == 0:
        targets = dict(space_policy.tier0_cleanup_targets())
    elif tier == 1:
        if not detect_pressure(data_dir).get("under_pressure") and trigger not in {"manual", "startup"}:
            return {"ok": True, "skipped": True, "reason": "no_pressure", "tier": tier, "trigger": trigger}
        targets = dict(space_policy.tier1_cleanup_targets())
    else:
        return {"ok": False, "error": "invalid_tier", "tier": tier}

    started = _utc_now()
    preflight = fleet_cleanup.snapshot_protected_containers()
    cleanup_out = fleet_cleanup.run_cleanup(
        data_dir,
        db_path,
        {"dry_run": dry_run, "targets": targets},
    )
    telemetry_out = _prune_telemetry(db_path) if tier == 0 and not dry_run else {"ok": True, "skipped": dry_run}
    postflight = fleet_cleanup.snapshot_protected_containers()
    integrity = fleet_cleanup.operational_integrity_check(preflight, postflight)
    integrity_ok = bool(integrity.get("ok", True))
    if not dry_run and not integrity_ok:
        cleanup_out["ok"] = False

    record = {
        "ok": cleanup_out.get("ok", True) and integrity_ok,
        "tier": tier,
        "tier_label": space_policy.tier_labels().get(tier, str(tier)),
        "trigger": trigger,
        "dry_run": dry_run,
        "started_at": started,
        "finished_at": _utc_now(),
        "bytes_freed_total": int(cleanup_out.get("bytes_freed_total") or 0),
        "operational_integrity_ok": integrity_ok,
        "operational_integrity": integrity,
        "telemetry": telemetry_out,
        "results": cleanup_out.get("results"),
        "skipped": False,
    }
    if skip:
        record["skip_guard"] = skip
    _append_run_log(data_dir, record)
    _ensure_space_runs_table(db_path)
    _insert_space_run(db_path, record)
    with _STATE_LOCK:
        global _LAST_RUN, _NEXT_RUN_EPOCH
        _LAST_RUN = dict(record)
        if not dry_run:
            jitter = random.uniform(0, min(600.0, space_policy.interval_s() * 0.05))
            _NEXT_RUN_EPOCH = time.time() + space_policy.interval_s() + jitter
    return record


def _ensure_space_runs_table(db_path: Path) -> None:
    conn = store.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS space_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                tier INTEGER NOT NULL,
                trigger TEXT,
                dry_run INTEGER NOT NULL,
                bytes_freed INTEGER,
                ok INTEGER,
                integrity_ok INTEGER,
                payload_json TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_space_run(db_path: Path, record: dict[str, Any]) -> None:
    conn = store.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO space_runs (started_at, tier, trigger, dry_run, bytes_freed, ok, integrity_ok, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.get("started_at"),
                int(record.get("tier") or 0),
                str(record.get("trigger") or ""),
                1 if record.get("dry_run") else 0,
                int(record.get("bytes_freed_total") or 0),
                1 if record.get("ok") else 0,
                1 if record.get("operational_integrity_ok") else 0,
                json.dumps(record, sort_keys=True),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def last_run() -> dict[str, Any] | None:
    with _STATE_LOCK:
        return dict(_LAST_RUN) if _LAST_RUN else None


def next_run_epoch() -> float | None:
    with _STATE_LOCK:
        return _NEXT_RUN_EPOCH


def space_status(data_dir: Path, db_path: Path) -> dict[str, Any]:
    from fleet_server import volume_quarantine

    pressure = detect_pressure(data_dir)
    nxt = next_run_epoch()
    vol_sync = volume_quarantine.refresh_registry(data_dir)
    return {
        "ok": True,
        "guardian_enabled": space_policy.guardian_enabled(),
        "interval_s": space_policy.interval_s(),
        "pressure": pressure,
        "tiers": space_policy.tier_labels(),
        "tier0_targets": list(space_policy.tier0_cleanup_targets().keys()),
        "tier1_targets": list(space_policy.tier1_cleanup_targets().keys()),
        "skip_reason": should_skip_run(db_path),
        "last_run": last_run(),
        "next_run_at": datetime.fromtimestamp(nxt, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if nxt else None,
        "next_run_in_s": max(0, int(nxt - time.time())) if nxt else None,
        "legacy_backup_roots": [str(p) for p in space_policy.legacy_backup_roots()],
        "volume_quarantine_days": space_policy.volume_quarantine_days(),
        "volumes": {
            "orphan_candidates": vol_sync.get("candidates") or [],
            "quarantine": volume_quarantine.registry_summary(data_dir),
        },
    }


def run_startup_gc(data_dir: Path, db_path: Path) -> None:
    """One-shot Tier 0 on Fleet boot (replaces inline GC in main)."""
    try:
        out = run_tier(data_dir, db_path, 0, dry_run=False, trigger="startup")
        if out.get("bytes_freed_total"):
            print(
                f"[fleet] space guardian startup freed {out.get('bytes_freed_total')} bytes "
                f"(integrity_ok={out.get('operational_integrity_ok')})"
            )
    except (OSError, sqlite3.Error, RuntimeError) as ex:
        print(f"[fleet] space guardian startup skipped: {ex}", file=sys.stderr)


def _guardian_loop(data_dir: Path, db_path: Path) -> None:
    jitter = random.uniform(30.0, 120.0)
    time.sleep(jitter)
    while True:
        try:
            skip = should_skip_run(db_path)
            if not skip:
                run_tier(data_dir, db_path, 0, dry_run=False, trigger="scheduled")
                if tier1_enabled():
                    pressure = detect_pressure(data_dir)
                    if pressure.get("under_pressure"):
                        run_tier(data_dir, db_path, 1, dry_run=False, trigger="pressure")
        except (OSError, sqlite3.Error, RuntimeError) as ex:
            print(f"[fleet] space guardian loop error: {ex}", file=sys.stderr)
        interval = space_policy.interval_s()
        jitter = random.uniform(0, min(600.0, interval * 0.05))
        with _STATE_LOCK:
            global _NEXT_RUN_EPOCH
            _NEXT_RUN_EPOCH = time.time() + interval + jitter
        time.sleep(interval + jitter)


def start_guardian(data_dir: Path, db_path: Path) -> None:
    global _THREAD
    if not space_policy.guardian_enabled():
        return
    with _RUN_LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        _THREAD = threading.Thread(
            target=_guardian_loop,
            args=(data_dir, db_path),
            name="fleet-space-guardian",
            daemon=True,
        )
        _THREAD.start()
