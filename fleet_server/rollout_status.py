"""Generic Fleet rollout maintenance/failure status files."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_DIR = Path.home() / ".local/state/forge-fleet" / "rollout-status"
LOG_DIR = Path.home() / ".local/state/forge-fleet" / "rollout-logs"

STEP_ESTIMATE_DEFAULTS_SEC: dict[str, int] = {
    "init": 5,
    "prepare": 30,
    "backup": 60,
    "sync": 60,
    "pause_jobs": 30,
    "drain_enrichment": 45,
    "build": 120,
    "source_copy": 15,
    "migrate": 30,
    "restart": 20,
    "health_check": 30,
    "resume_jobs": 20,
    "register": 5,
    "finalize": 10,
}


def _status_path(service_id: str) -> Path:
    sid = str(service_id or "").strip()
    if not sid:
        raise ValueError("service_id_required")
    return STATUS_DIR / f"{sid}.json"


def _log_path(service_id: str) -> Path:
    sid = str(service_id or "").strip()
    if not sid:
        raise ValueError("service_id_required")
    return LOG_DIR / f"{sid}.log"


def _idle_status(service_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "service_id": service_id,
        "maintenance": False,
        "failed": False,
    }


def _progress_pct(data: dict[str, Any]) -> int:
    if not data.get("maintenance"):
        return 0
    total = len(STEP_ESTIMATE_DEFAULTS_SEC)
    if total <= 0:
        return 0
    done = len({str(s) for s in (data.get("steps_done") or []) if str(s)})
    current = str(data.get("current_step") or "")
    if current and current not in {str(s) for s in (data.get("steps_done") or [])}:
        done = min(total, done + 1)
    return max(0, min(100, int(round(100 * done / total))))


def _job_id_from_slot(service_id: str, data: dict[str, Any]) -> str | None:
    existing = str(data.get("job_id") or "").strip()
    if existing:
        return existing
    if not data.get("maintenance") and not data.get("failed"):
        return None
    from fleet_server import rollout_slot

    slot = rollout_slot.read_slot(service_id)
    if not slot.get("held"):
        return None
    if str(slot.get("holder_kind") or "job") != "job":
        return None
    holder = str(slot.get("holder") or "").strip()
    return holder or None


def _estimate_remaining_sec(data: dict[str, Any]) -> int:
    if not data.get("maintenance"):
        return 0
    current = str(data.get("current_step") or "")
    steps_done = {str(s) for s in (data.get("steps_done") or [])}
    remaining = 0
    seen_current = False
    for step_id, sec in STEP_ESTIMATE_DEFAULTS_SEC.items():
        if step_id == current:
            seen_current = True
            remaining += sec
            continue
        if seen_current and step_id not in steps_done:
            remaining += sec
    if remaining <= 0 and current:
        remaining = STEP_ESTIMATE_DEFAULTS_SEC.get(current, 30)
    return remaining


def read_rollout_status(service_id: str) -> dict[str, Any]:
    sid = str(service_id or "").strip()
    if not sid:
        return {"ok": False, "error": "service_id_required"}
    path = _status_path(sid)
    if not path.is_file():
        return _idle_status(sid)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "service_id": sid, "error": "status_read_failed", "detail": str(exc)[:400]}
    if not isinstance(data, dict):
        return {"ok": False, "service_id": sid, "error": "status_invalid"}
    out = {
        "ok": True,
        "service_id": sid,
        "maintenance": bool(data.get("maintenance")),
        "failed": bool(data.get("failed")),
        "started_at": data.get("started_at"),
        "updated_at": data.get("updated_at"),
        "failed_at": data.get("failed_at"),
        "current_step": data.get("current_step"),
        "current_step_label": data.get("current_step_label"),
        "steps_done": list(data.get("steps_done") or []),
        "failed_step": data.get("failed_step"),
        "error": data.get("error") or "",
        "log_tail": data.get("log_tail") or "",
        "eta_sec": _estimate_remaining_sec(data),
        "progress_pct": _progress_pct(data),
    }
    if data.get("backup_path"):
        out["backup_path"] = data.get("backup_path")
    if data.get("backup_verified") is not None:
        out["backup_verified"] = bool(data.get("backup_verified"))
    if data.get("backup_bytes") is not None:
        out["backup_bytes"] = data.get("backup_bytes")
    job_id = _job_id_from_slot(sid, data)
    if job_id:
        out["job_id"] = job_id
    return out


def clear_rollout_status(service_id: str) -> dict[str, Any]:
    sid = str(service_id or "").strip()
    if not sid:
        return {"ok": False, "error": "service_id_required"}
    path = _status_path(sid)
    if path.is_file():
        path.unlink()
    return {"ok": True, "service_id": sid, "cleared": True}


def read_rollout_log(service_id: str, *, max_bytes: int = 16000) -> dict[str, Any]:
    sid = str(service_id or "").strip()
    if not sid:
        return {"ok": False, "error": "service_id_required"}
    path = _log_path(sid)
    if not path.is_file():
        return {"ok": True, "service_id": sid, "log_path": str(path), "log": "", "exists": False}
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return {
        "ok": True,
        "service_id": sid,
        "log_path": str(path),
        "exists": True,
        "log": data.decode("utf-8", errors="replace"),
    }


def patch_rollout_status(service_id: str, fields: dict[str, Any]) -> None:
    sid = str(service_id or "").strip()
    if not sid or not fields:
        return
    path = _status_path(sid)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data.update(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_rollout_failure(
    service_id: str,
    *,
    failed_step: str,
    error: str,
    log_tail: str = "",
    steps_done: list[str] | None = None,
) -> dict[str, Any]:
    sid = str(service_id or "").strip()
    if not sid:
        return {"ok": False, "error": "service_id_required"}
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = _status_path(sid)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    done = list(steps_done or data.get("steps_done") or [])
    prev = str(data.get("current_step") or "")
    if prev and prev != failed_step and prev not in done:
        done.append(prev)
    payload = {
        "service_id": sid,
        "maintenance": False,
        "failed": True,
        "started_at": data.get("started_at") or now,
        "updated_at": now,
        "failed_at": now,
        "current_step": failed_step,
        "current_step_label": data.get("current_step_label") or failed_step,
        "steps_done": done,
        "failed_step": failed_step,
        "error": error,
        "log_tail": log_tail,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True, "service_id": sid, "failed": True, "failed_step": failed_step}
