"""Per-service rollout slot: one mutating rollout/rollback/replicate at a time."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fleet_server import infra_flows, rollout_status

SERIALIZED_CATEGORIES = frozenset({"rollout", "rollback", "replicate"})
SLOTS_DIR = Path.home() / ".local/state/forge-fleet" / "rollout-slots"
SLOT_TTL_SEC = 4 * 3600
_RETRY_AFTER_SEC = 30

_LOCKS: dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class RolloutTarget:
    environment: str
    service_id: str


def normalize_env_id(raw: str) -> str:
    val = str(raw or "").strip()
    if "--" in val:
        return val.split("--", 1)[1].strip().lower()
    return val.lower()


def _slot_lock(service_id: str) -> threading.Lock:
    sid = str(service_id or "").strip()
    if sid not in _LOCKS:
        _LOCKS[sid] = threading.Lock()
    return _LOCKS[sid]


def _slot_path(service_id: str) -> Path:
    sid = str(service_id or "").strip()
    if not sid:
        raise ValueError("service_id_required")
    return SLOTS_DIR / f"{sid}.json"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_slot_file(service_id: str) -> dict[str, Any] | None:
    path = _slot_path(service_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def read_slot(service_id: str) -> dict[str, Any]:
    sid = str(service_id or "").strip()
    doc = _read_slot_file(sid)
    if doc is None:
        return {"ok": True, "service_id": sid, "held": False}
    return {
        "ok": True,
        "service_id": sid,
        "held": True,
        "holder": doc.get("holder"),
        "holder_kind": doc.get("holder_kind"),
        "environment": doc.get("environment"),
        "acquired_at": doc.get("acquired_at"),
    }


def _slot_age_sec(doc: dict[str, Any]) -> float:
    raw = str(doc.get("acquired_at") or "")
    if not raw:
        return 0.0
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return max(0.0, time.time() - dt.timestamp())
    except ValueError:
        return 0.0


def _job_active(conn: Any, job_id: str) -> bool:
    if not job_id or not conn:
        return False
    from fleet_server import store

    row = store.get_job(conn, job_id)
    if row is None:
        return False
    return str(row.get("status") or "") in ("queued", "running")


def _find_active_job(conn: Any, service_id: str) -> str | None:
    if conn is None:
        return None
    from fleet_server import store

    return store.find_active_rollout_job(conn, service_id)


def _holder_still_active(
    service_id: str,
    doc: dict[str, Any],
    *,
    db_path: Path | None = None,
) -> bool:
    holder = str(doc.get("holder") or "")
    kind = str(doc.get("holder_kind") or "job")
    if not holder:
        return False
    if _slot_age_sec(doc) > SLOT_TTL_SEC:
        return False

    if kind == "legacy":
        return True

    if db_path is None:
        return True

    from fleet_server import store

    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, holder)
        if row is None:
            return True
        if str(row.get("status") or "") in ("queued", "running"):
            return True
        maint = rollout_status.read_rollout_status(service_id)
        if bool(maint.get("maintenance")):
            return True
        if _find_active_job(conn, service_id):
            return True
    finally:
        conn.close()
    return False


def conflict_response(
    service_id: str,
    *,
    active_job_id: str | None = None,
    holder: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "rollout_in_progress",
        "service_id": service_id,
        "active_job_id": active_job_id or holder,
        "retry_after_sec": _RETRY_AFTER_SEC,
    }


def resolve_rollout_target(flow_id: str, inputs: dict[str, Any]) -> RolloutTarget | None:
    fid = str(flow_id or "").strip()
    meta = infra_flows._FLOW_CATALOG.get(fid)  # noqa: SLF001 — catalog is module-private
    if meta is None:
        return None
    category = str(meta.get("category") or "")
    if category not in SERIALIZED_CATEGORIES:
        return None

    env_raw = ""
    if fid == "environment-replicate":
        env_raw = str(inputs.get("target_environment") or "")
    else:
        env_raw = str(inputs.get("environment") or "")
    environment = normalize_env_id(env_raw)
    if not environment:
        return None

    if fid.startswith("market-studio") or fid == "environment-replicate":
        from fleet_server.market_studio_rollout_env import rollout_identity

        service_id, _ = rollout_identity(environment)
        return RolloutTarget(environment=environment, service_id=service_id)

    return None


def try_acquire(
    service_id: str,
    holder: str,
    *,
    environment: str | None = None,
    holder_kind: str = "job",
    db_path: Path | None = None,
) -> dict[str, Any]:
    sid = str(service_id or "").strip()
    hid = str(holder or "").strip()
    if not sid or not hid:
        return {"ok": False, "error": "service_id_and_holder_required"}

    with _slot_lock(sid):
        existing = _read_slot_file(sid)
        if existing:
            active_job = str(existing.get("holder") or "")
            if _holder_still_active(sid, existing, db_path=db_path):
                if str(existing.get("holder") or "") != hid:
                    aj = active_job if str(existing.get("holder_kind") or "job") == "job" else None
                    if db_path is not None:
                        from fleet_server import store

                        conn = store.connect(db_path)
                        try:
                            aj = aj or _find_active_job(conn, sid)
                        finally:
                            conn.close()
                    return conflict_response(sid, active_job_id=aj, holder=active_job)
            else:
                _slot_path(sid).unlink(missing_ok=True)

        doc = {
            "service_id": sid,
            "holder": hid,
            "holder_kind": holder_kind,
            "environment": normalize_env_id(environment or ""),
            "acquired_at": _utc_now(),
        }
        _write_json_atomic(_slot_path(sid), doc)
        return {"ok": True, "service_id": sid, "holder": hid}


def release(service_id: str, holder: str) -> None:
    sid = str(service_id or "").strip()
    hid = str(holder or "").strip()
    if not sid:
        return
    with _slot_lock(sid):
        existing = _read_slot_file(sid)
        if existing is None:
            return
        if hid and str(existing.get("holder") or "") != hid:
            return
        _slot_path(sid).unlink(missing_ok=True)


def new_legacy_holder() -> str:
    return f"legacy-{uuid.uuid4().hex[:16]}"


def release_for_job(db_path: Path, job_id: str) -> None:
    """Release rollout slot when a Fleet job reaches a terminal state."""
    from fleet_server import store

    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
        if row is None:
            return
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        svc = str(meta.get("rollout_service_id") or "")
        if svc:
            release(svc, job_id)
    finally:
        conn.close()
