"""Fleet process lifecycle: drain, stop-readiness, in-flight counters."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import store

_LOCK = threading.Lock()
_DRAINING = False
_UPGRADE_ID: str | None = None
_STARTUP_READY = False
_PROXY_INFLIGHT = 0
_PROXY_LOCK = threading.Lock()


def mark_startup_ready() -> None:
    global _STARTUP_READY
    _STARTUP_READY = True


def is_startup_ready() -> bool:
    return _STARTUP_READY


def set_draining(value: bool, *, upgrade_id: str | None = None) -> None:
    global _DRAINING, _UPGRADE_ID
    with _LOCK:
        _DRAINING = bool(value)
        _UPGRADE_ID = upgrade_id if value else None


def is_draining() -> bool:
    with _LOCK:
        return _DRAINING


def upgrade_id() -> str | None:
    with _LOCK:
        return _UPGRADE_ID


def resume() -> None:
    set_draining(False)


def proxy_enter() -> None:
    global _PROXY_INFLIGHT
    with _PROXY_LOCK:
        _PROXY_INFLIGHT += 1


def proxy_exit() -> None:
    global _PROXY_INFLIGHT
    with _PROXY_LOCK:
        _PROXY_INFLIGHT = max(0, _PROXY_INFLIGHT - 1)


def proxy_inflight() -> int:
    with _PROXY_LOCK:
        return _PROXY_INFLIGHT


def wait_proxy_drain(timeout_sec: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_sec)
    while time.monotonic() < deadline:
        if proxy_inflight() == 0:
            return True
        time.sleep(0.1)
    return proxy_inflight() == 0


def _running_job_blockers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT id, status FROM jobs WHERE status IN ('running', 'queued') LIMIT 50"
    ).fetchall()
    for row in rows:
        blockers.append(
            {
                "kind": "fleet_job",
                "id": str(row[0]),
                "detail": str(row[1]),
            }
        )
    return blockers


def _rollout_slot_blockers(data_dir: Path) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    slots_dir = Path.home() / ".local/state/forge-fleet/rollout-slots"
    if not slots_dir.is_dir():
        return blockers
    for path in sorted(slots_dir.glob("*.json")):
        try:
            import json

            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict) and doc.get("held"):
            blockers.append(
                {
                    "kind": "rollout_slot",
                    "id": path.stem,
                    "detail": str(doc.get("holder") or ""),
                }
            )
    return blockers


def stop_readiness_payload(db_path: Path, data_dir: Path) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not is_startup_ready():
        blockers.append({"kind": "startup", "detail": "migrations_or_warmup"})
    inflight = proxy_inflight()
    if inflight > 0:
        blockers.append({"kind": "app_gateway_proxy", "count": inflight, "detail": "in_flight"})
    conn = store.connect(db_path)
    try:
        blockers.extend(_running_job_blockers(conn))
    finally:
        conn.close()
    blockers.extend(_rollout_slot_blockers(data_dir))
    stop_allowed = len(blockers) == 0
    reason = "idle"
    if not stop_allowed:
        reason = "active_work"
    elif is_draining():
        reason = "drained"
    return {
        "ok": True,
        "service_id": "forge-fleet",
        "stop_allowed": stop_allowed,
        "reason": reason,
        "retry_after_sec": 0 if stop_allowed else 5,
        "draining": is_draining(),
        "blockers": blockers,
        "ready": is_startup_ready() and not is_draining(),
    }


def prepare_stop(body: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(body or {})
    uid = str(raw.get("upgrade_id") or "").strip() or None
    already = is_draining()
    set_draining(True, upgrade_id=uid)
    return {
        "ok": True,
        "accepted": True,
        "already_draining": already,
        "service_id": "forge-fleet",
    }


def health_extensions() -> dict[str, Any]:
    return {
        "draining": is_draining(),
        "ready": is_startup_ready() and not is_draining(),
    }


def stop_grace_sec() -> float:
    raw = str(os.environ.get("FLEET_STOP_GRACE_SEC", "25") or "25").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 25.0
