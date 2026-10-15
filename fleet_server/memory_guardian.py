"""Memory Guardian — idle service parking and wake-on-request (in-process daemon)."""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fleet_server import capacity_policy, container_layout, managed_compose_service as mcs
from fleet_server import space_guardian


_RUN_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_WAKE_LOCK = threading.Lock()
_LAST_RUN: dict[str, Any] | None = None
_NEXT_RUN_EPOCH: float | None = None
_THREAD: threading.Thread | None = None
_DETAIL_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_DETAIL_CACHE_TTL_S = 15.0


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def memory_dir(data_dir: Path) -> Path:
    return data_dir / "memory"


def activity_path(data_dir: Path) -> Path:
    return memory_dir(data_dir) / "activity.json"


def runs_log_path(data_dir: Path) -> Path:
    return memory_dir(data_dir) / "runs.jsonl"


def _read_activity(data_dir: Path) -> dict[str, float]:
    path = activity_path(data_dir)
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    out: dict[str, float] = {}
    for key, val in doc.items():
        try:
            out[str(key)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def record_activity(data_dir: Path, key: str, *, when: float | None = None) -> None:
    k = str(key or "").strip()
    if not k:
        return
    path = activity_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = _read_activity(data_dir)
    doc[k] = float(when if when is not None else time.time())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _mem_available_bytes() -> int | None:
    from fleet_server import host_stats

    snap = host_stats.snapshot()
    mem = snap.get("memory") if isinstance(snap.get("memory"), dict) else {}
    try:
        avail_kb = int(mem.get("available_kb"))
    except (TypeError, ValueError):
        return None
    return avail_kb * 1024


def detect_memory_pressure(data_dir: Path) -> dict[str, Any]:
    avail = _mem_available_bytes()
    floor = capacity_policy.memory_free_ram_floor_bytes(data_dir)
    under = avail is not None and avail < floor
    return {
        "available_bytes": avail,
        "floor_bytes": floor,
        "under_pressure": bool(under),
    }


def should_skip_run(db_path: Path, data_dir: Path) -> str | None:
    if not capacity_policy.env_memory_guardian_default():
        return "memory_guardian_disabled_env"
    if not capacity_policy.memory_loop_enabled(data_dir):
        return "memory_guardian_disabled"
    reason = space_guardian.should_skip_run(db_path, data_dir)
    if reason in {"fleet_draining", "upgrade_active", "rollout_in_progress"}:
        return reason
    return None


def _class_for_service_id(data_dir: Path, service_id: str) -> str:
    policy = capacity_policy.load_policy(data_dir)
    mem = policy.get("memory") if isinstance(policy.get("memory"), dict) else {}
    sid = str(service_id or "").strip()
    pinned = {str(x) for x in (mem.get("pinned_service_ids") or [])}
    warm = {str(x) for x in (mem.get("warm_service_ids") or [])}
    if sid in pinned:
        return "pinned"
    if sid in warm:
        return "warm"
    return "unknown"


def _ollama_port_open() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/", timeout=1.5) as resp:
            return 200 <= int(resp.status) < 500
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _systemd_user_unit_exists(unit: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "status", unit],
            capture_output=True,
            text=True,
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode in (0, 3)


def _systemd_user_active(unit: str) -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=8.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and (r.stdout or "").strip() == "active"


def _systemd_user_start(unit: str) -> dict[str, Any]:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "start", unit],
            capture_output=True,
            text=True,
            timeout=120.0,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "error": type(ex).__name__, "detail": str(ex)[:400]}
    return {"ok": r.returncode == 0, "stdout": (r.stdout or "")[:200], "stderr": (r.stderr or "")[:400]}


def _systemd_user_stop(unit: str) -> dict[str, Any]:
    try:
        r = subprocess.run(
            ["systemctl", "--user", "stop", unit],
            capture_output=True,
            text=True,
            timeout=90.0,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "error": type(ex).__name__, "detail": str(ex)[:400]}
    return {"ok": r.returncode == 0, "stdout": (r.stdout or "")[:200], "stderr": (r.stderr or "")[:400]}


def _touch_from_gateway_stats(data_dir: Path) -> None:
    for rec in container_layout.list_service_records(data_dir):
        if str(rec.get("type_id")) != "forge_llm":
            continue
        st = mcs.status_for_record(rec)
        rows, _ = mcs.compose_ps(
            Path(str(st.get("compose_root") or "")),
            list(st.get("compose_files") or []),
        )
        from fleet_server import forge_llm_service

        gw = forge_llm_service.gateway_host_port_from_compose_ps(rows)
        if not gw:
            continue
        cp = forge_llm_service.fetch_gateway_control_plane(int(gw["host_port"]), hours=1.0)
        if not cp:
            continue
        rollup = cp.get("rollup") if isinstance(cp.get("rollup"), dict) else {}
        try:
            reqs = int(rollup.get("requests") or 0)
        except (TypeError, ValueError):
            reqs = 0
        if reqs > 0:
            record_activity(data_dir, f"forge_llm:{rec.get('id')}")


def _service_row(data_dir: Path, rec: dict[str, Any], activity: dict[str, float]) -> dict[str, Any]:
    sid = str(rec.get("id") or "")
    key = f"compose:{sid}"
    st = mcs.status_for_record(rec)
    running = int(st.get("services_running") or 0) > 0
    last = activity.get(key)
    now = time.time()
    idle_s = (now - last) if last is not None else None
    cls = _class_for_service_id(data_dir, sid)
    return {
        "id": sid,
        "label": rec.get("label"),
        "type_id": rec.get("type_id"),
        "class": cls,
        "running": running,
        "services_running": st.get("services_running"),
        "services_total": st.get("services_total"),
        "last_activity_epoch": last,
        "idle_seconds": round(idle_s, 1) if idle_s is not None else None,
        "activity_key": key,
    }


def _cold_rows(data_dir: Path, activity: dict[str, float]) -> list[dict[str, Any]]:
    policy = capacity_policy.load_policy(data_dir)
    mem = policy.get("memory") if isinstance(policy.get("memory"), dict) else {}
    rows: list[dict[str, Any]] = []
    now = time.time()
    for raw in mem.get("cold_targets") or []:
        if not isinstance(raw, dict):
            continue
        cid = str(raw.get("id") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        key = f"cold:{cid}"
        last = activity.get(key)
        idle_s = (now - last) if last is not None else None
        if kind == "systemd_user":
            unit = str(raw.get("unit") or "").strip()
            exists = _systemd_user_unit_exists(unit) if unit else False
            running = _systemd_user_active(unit) if unit and exists else _ollama_port_open()
            rows.append(
                {
                    "id": cid,
                    "class": "cold",
                    "kind": kind,
                    "unit": unit,
                    "unit_present": exists,
                    "running": running,
                    "last_activity_epoch": last,
                    "idle_seconds": round(idle_s, 1) if idle_s is not None else None,
                    "activity_key": key,
                }
            )
        elif kind == "compose_service":
            rows.append(
                {
                    "id": cid,
                    "class": "cold",
                    "kind": kind,
                    "service_name": raw.get("service_name"),
                    "running": None,
                    "last_activity_epoch": last,
                    "idle_seconds": round(idle_s, 1) if idle_s is not None else None,
                    "activity_key": key,
                }
            )
    return rows


def _plan_stops(data_dir: Path) -> list[dict[str, Any]]:
    policy = capacity_policy.load_policy(data_dir)
    mem = policy.get("memory") if isinstance(policy.get("memory"), dict) else {}
    pressure = detect_memory_pressure(data_dir)
    activity = _read_activity(data_dir)
    cold_idle = capacity_policy.memory_idle_seconds(data_dir, warm=False)
    warm_idle = capacity_policy.memory_idle_seconds(data_dir, warm=True)
    plan: list[dict[str, Any]] = []
    for rec in container_layout.list_service_records(data_dir):
        row = _service_row(data_dir, rec, activity)
        cls = row["class"]
        if cls == "pinned" or cls == "unknown":
            continue
        if not row.get("running"):
            continue
        idle = row.get("idle_seconds")
        if idle is None or idle < (warm_idle if cls == "warm" else cold_idle):
            continue
        if cls == "warm" and not pressure.get("under_pressure"):
            continue
        plan.append({**row, "action": "stop", "reason": f"idle_{cls}"})
    for crow in _cold_rows(data_dir, activity):
        if not crow.get("running"):
            continue
        idle = crow.get("idle_seconds")
        if idle is None or idle < cold_idle:
            continue
        plan.append({**crow, "action": "stop", "reason": "idle_cold"})
    return plan


def _stop_compose_service(data_dir: Path, service_id: str) -> dict[str, Any]:
    rec = container_layout.read_service(data_dir, service_id)
    if rec is None:
        return {"ok": False, "error": "not_found"}
    out = mcs.stop_for_record(rec)
    return {"ok": True, "detail": out}


def _start_compose_service(data_dir: Path, service_id: str) -> dict[str, Any]:
    rec = container_layout.read_service(data_dir, service_id)
    if rec is None:
        return {"ok": False, "error": "not_found"}
    out = mcs.start_for_record(rec)
    record_activity(data_dir, f"compose:{service_id}")
    return {"ok": True, "detail": out}


def run_tier(
    data_dir: Path,
    db_path: Path,
    tier: int,
    *,
    dry_run: bool = True,
    trigger: str = "manual",
    service_id: str | None = None,
) -> dict[str, Any]:
    skip = should_skip_run(db_path, data_dir)
    if skip:
        return {"ok": True, "skipped": True, "reason": skip, "tier": tier, "dry_run": dry_run}
    started = _utc_now()
    pressure = detect_memory_pressure(data_dir)
    plan = _plan_stops(data_dir)
    if tier >= 2 and service_id:
        sid = str(service_id).strip()
        plan = [{"id": sid, "action": "stop", "reason": "manual_tier2", "class": _class_for_service_id(data_dir, sid)}]
    applied: list[dict[str, Any]] = []
    manual_tier2 = tier >= 2 and bool(service_id)
    if not dry_run and manual_tier2:
        for item in plan:
            iid = str(item.get("id") or "")
            if item.get("kind") == "systemd_user":
                unit = str(item.get("unit") or "ollama.service")
                applied.append({**item, **_systemd_user_stop(unit)})
                continue
            if iid:
                applied.append({**item, **_stop_compose_service(data_dir, iid)})
    elif not dry_run and tier == 1 and capacity_policy.memory_apply_stops(data_dir):
        for item in plan:
            if item.get("class") == "pinned":
                applied.append({**item, "ok": False, "error": "pinned"})
                continue
            iid = str(item.get("id") or "")
            if item.get("kind") == "systemd_user":
                unit = str(item.get("unit") or "ollama.service")
                res = _systemd_user_stop(unit)
                applied.append({**item, **res})
                continue
            if iid:
                res = _stop_compose_service(data_dir, iid)
                applied.append({**item, **res})
    elif not dry_run and tier == 1 and not capacity_policy.memory_apply_stops(data_dir):
        return {
            "ok": True,
            "skipped": True,
            "reason": "apply_stops_disabled",
            "tier": tier,
            "pressure": pressure,
            "plan": plan,
        }
    record = {
        "started_at": started,
        "finished_at": _utc_now(),
        "tier": tier,
        "dry_run": dry_run,
        "trigger": trigger,
        "pressure": pressure,
        "plan": plan,
        "applied": applied,
    }
    _append_run_log(data_dir, record)
    with _STATE_LOCK:
        global _LAST_RUN
        _LAST_RUN = record
    return {"ok": True, **record}


def _append_run_log(data_dir: Path, record: dict[str, Any]) -> None:
    path = runs_log_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def last_run() -> dict[str, Any] | None:
    with _STATE_LOCK:
        return dict(_LAST_RUN) if isinstance(_LAST_RUN, dict) else None


def next_run_epoch() -> float | None:
    with _STATE_LOCK:
        return _NEXT_RUN_EPOCH


def memory_meta_summary(data_dir: Path, db_path: Path) -> dict[str, Any]:
    """Compact fields for admin snapshot — no docker stats fan-out."""
    pressure = detect_memory_pressure(data_dir)
    last = last_run() or {}
    nxt = next_run_epoch()
    return {
        "guardian_enabled": capacity_policy.memory_loop_enabled(data_dir),
        "apply_stops": capacity_policy.memory_apply_stops(data_dir),
        "under_pressure": pressure.get("under_pressure"),
        "available_bytes": pressure.get("available_bytes"),
        "floor_bytes": pressure.get("floor_bytes"),
        "last_run_at": last.get("started_at"),
        "last_plan_count": len(last.get("plan") or []) if isinstance(last.get("plan"), list) else 0,
        "next_run_in_s": max(0, int(nxt - time.time())) if nxt else None,
        "skip_reason": should_skip_run(db_path, data_dir),
    }


def memory_status(data_dir: Path, db_path: Path, *, use_cache: bool = True) -> dict[str, Any]:
    now = time.time()
    if use_cache:
        cached = _DETAIL_CACHE.get("payload")
        if cached is not None and (now - float(_DETAIL_CACHE.get("ts") or 0)) < _DETAIL_CACHE_TTL_S:
            return json.loads(json.dumps(cached))
    _touch_from_gateway_stats(data_dir)
    activity = _read_activity(data_dir)
    from fleet_server import host_stats

    host = host_stats.snapshot()
    gpu = host.get("gpu") if isinstance(host.get("gpu"), dict) else {}
    services = [_service_row(data_dir, rec, activity) for rec in container_layout.list_service_records(data_dir)]
    payload = {
        "ok": True,
        "guardian_enabled": capacity_policy.memory_loop_enabled(data_dir),
        "apply_stops": capacity_policy.memory_apply_stops(data_dir),
        "policy": capacity_policy.load_policy(data_dir),
        "pressure": detect_memory_pressure(data_dir),
        "host_memory": host.get("memory"),
        "gpu_summary": {
            "nvidia_available": bool((gpu.get("nvidia") or {}).get("available"))
            if isinstance(gpu.get("nvidia"), dict)
            else False,
            "nvidia_reason": (gpu.get("nvidia") or {}).get("reason")
            if isinstance(gpu.get("nvidia"), dict)
            else None,
        },
        "services": services,
        "cold_targets": _cold_rows(data_dir, activity),
        "plan": _plan_stops(data_dir),
        "skip_reason": should_skip_run(db_path, data_dir),
        "last_run": last_run(),
        "next_run_in_s": max(0, int((next_run_epoch() or 0) - time.time())) if next_run_epoch() else None,
    }
    with _STATE_LOCK:
        _DETAIL_CACHE["ts"] = now
        _DETAIL_CACHE["payload"] = payload
    return payload


def ensure_running(data_dir: Path, target_id: str, *, wait_sec: float = 90.0) -> dict[str, Any]:
    tid = str(target_id or "").strip() or "host-ollama"
    with _WAKE_LOCK:
        policy = capacity_policy.load_policy(data_dir)
        mem = policy.get("memory") if isinstance(policy.get("memory"), dict) else {}
        cold = mem.get("cold_targets") or []
        match: dict[str, Any] | None = None
        for row in cold:
            if isinstance(row, dict) and str(row.get("id")) == tid:
                match = row
                break
        if match is None and tid == "host-ollama":
            for row in cold:
                if isinstance(row, dict) and row.get("kind") == "systemd_user":
                    match = row
                    break
        if match is None:
            return {"ok": False, "error": "unknown_target", "target_id": tid}
        pressure = detect_memory_pressure(data_dir)
        if pressure.get("under_pressure"):
            warm_plan = [p for p in _plan_stops(data_dir) if p.get("class") == "warm"]
            for item in warm_plan[:3]:
                sid = str(item.get("id") or "")
                if sid:
                    _stop_compose_service(data_dir, sid)
        kind = str(match.get("kind") or "")
        key = f"cold:{match.get('id')}"
        if kind == "systemd_user":
            unit = str(match.get("unit") or "ollama.service")
            if not _systemd_user_unit_exists(unit):
                return {"ok": False, "error": "unit_missing", "unit": unit}
            if not _systemd_user_active(unit):
                start = _systemd_user_start(unit)
                if not start.get("ok"):
                    return {"ok": False, "error": "start_failed", **start}
            deadline = time.time() + max(5.0, wait_sec)
            while time.time() < deadline:
                if _ollama_port_open():
                    record_activity(data_dir, key)
                    return {"ok": True, "target_id": tid, "running": True, "unit": unit}
                time.sleep(2.0)
            return {"ok": False, "error": "timeout", "target_id": tid}
        record_activity(data_dir, key)
        return {"ok": False, "error": "unsupported_kind", "kind": kind}


def _guardian_loop(data_dir: Path, db_path: Path) -> None:
    jitter = random.uniform(30.0, 120.0)
    time.sleep(jitter)
    while True:
        try:
            skip = should_skip_run(db_path, data_dir)
            if not skip:
                run_tier(data_dir, db_path, 0, dry_run=True, trigger="scheduled")
                if capacity_policy.memory_apply_stops(data_dir):
                    run_tier(data_dir, db_path, 1, dry_run=False, trigger="scheduled")
        except (OSError, RuntimeError) as ex:
            print(f"[fleet] memory guardian loop error: {ex}", file=sys.stderr)
        try:
            interval = max(300.0, float(os.environ.get("FLEET_MEMORY_INTERVAL_S") or "3600"))
        except ValueError:
            interval = 3600.0
        jitter = random.uniform(0, min(600.0, interval * 0.05))
        with _STATE_LOCK:
            global _NEXT_RUN_EPOCH
            _NEXT_RUN_EPOCH = time.time() + interval + jitter
        time.sleep(interval + jitter)


def start_guardian(data_dir: Path, db_path: Path) -> None:
    global _THREAD
    if not capacity_policy.env_memory_guardian_default():
        return
    with _RUN_LOCK:
        if _THREAD and _THREAD.is_alive():
            return
        _THREAD = threading.Thread(
            target=_guardian_loop,
            args=(data_dir, db_path),
            name="fleet-memory-guardian",
            daemon=True,
        )
        _THREAD.start()
