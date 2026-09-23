"""Cooperative upgrade coordinator: prepare dependents, poll stop-readiness, persist status."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, request

from fleet_server import lifecycle
from fleet_server.lifecycle_registry import LifecycleDependent, list_dependents

_STATUS_DIR = Path.home() / ".local/state/forge-fleet/upgrade"
_ACTIVE_FILE = _STATUS_DIR / "active.json"
_LOCK = threading.Lock()


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _http_json(method: str, url: str, body: dict[str, Any] | None = None, timeout_s: float = 5.0) -> tuple[int, dict[str, Any] | None]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = int(getattr(resp, "status", 200) or 200)
    except error.HTTPError as exc:
        code = int(exc.code)
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
    except (error.URLError, OSError, TimeoutError):
        return 0, None
    if not raw.strip():
        return code, {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return code, None
    return code, parsed if isinstance(parsed, dict) else {}


def read_status() -> dict[str, Any]:
    if not _ACTIVE_FILE.is_file():
        return {"ok": True, "phase": "idle"}
    try:
        doc = json.loads(_ACTIVE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": True, "phase": "idle"}
    return doc if isinstance(doc, dict) else {"ok": True, "phase": "idle"}


def clear_status() -> None:
    with _LOCK:
        if _ACTIVE_FILE.is_file():
            _ACTIVE_FILE.unlink(missing_ok=True)


def _update_status(**fields: Any) -> dict[str, Any]:
    with _LOCK:
        doc = read_status()
        if doc.get("phase") == "idle":
            doc = {"ok": True, "phase": "idle"}
        doc.update(fields)
        doc["updated_at"] = _utc_now()
        _write_json_atomic(_ACTIVE_FILE, doc)
        return doc


def aggregate_readiness(db_path: Path, data_dir: Path) -> dict[str, Any]:
    fleet_self = lifecycle.stop_readiness_payload(db_path, data_dir)
    waiting: list[dict[str, Any]] = []
    all_ok = bool(fleet_self.get("stop_allowed"))
    if not all_ok:
        waiting.append({"service_id": "forge-fleet", "blockers": fleet_self.get("blockers") or []})
    for dep in list_dependents():
        code, body = _http_json("GET", dep.readiness_url)
        if code == 0 or body is None:
            if not dep.optional:
                all_ok = False
                waiting.append({"service_id": dep.service_id, "blockers": [{"kind": "unreachable"}]})
            continue
        if not body.get("stop_allowed", True):
            all_ok = False
            waiting.append(
                {
                    "service_id": dep.service_id,
                    "blockers": body.get("blockers") or [],
                    "reason": body.get("reason"),
                }
            )
    return {
        "ok": True,
        "stop_allowed": all_ok,
        "fleet": fleet_self,
        "waiting_on": waiting,
    }


def _prepare_all(upgrade_id: str, body: dict[str, Any]) -> None:
    prep_body = {
        "upgrade_id": upgrade_id,
        "deadline_utc": body.get("deadline_utc"),
        "reason": body.get("reason") or "fleet_upgrade",
        "mode": body.get("mode") or "upgrade",
    }
    lifecycle.prepare_stop(prep_body)
    for dep in list_dependents():
        _http_json("POST", dep.prepare_url, prep_body)


def wait_for_readiness(
    db_path: Path,
    data_dir: Path,
    *,
    max_wait_sec: int,
    on_timeout: str,
    upgrade_id: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, max_wait_sec)
    while time.monotonic() < deadline:
        agg = aggregate_readiness(db_path, data_dir)
        waiting = agg.get("waiting_on") or []
        _update_status(
            phase="waiting_on_services",
            upgrade_id=upgrade_id,
            waiting_on=waiting,
            deadline_sec=max(0, int(deadline - time.monotonic())),
        )
        if agg.get("stop_allowed"):
            return {"ok": True, "stop_allowed": True, "waiting_on": []}
        retry = 5
        for w in waiting:
            pass
        time.sleep(min(retry, max(1, int(deadline - time.monotonic()))))
    agg = aggregate_readiness(db_path, data_dir)
    if agg.get("stop_allowed"):
        return {"ok": True, "stop_allowed": True, "waiting_on": []}
    if str(on_timeout or "abort").lower() == "force":
        return {"ok": True, "stop_allowed": True, "forced": True, "waiting_on": agg.get("waiting_on") or []}
    return {
        "ok": False,
        "error": "upgrade_blocked",
        "waiting_on": agg.get("waiting_on") or [],
    }


def begin_upgrade(body: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(body or {})
    mode = str(raw.get("mode") or "upgrade").strip().lower()
    if mode not in ("update", "upgrade"):
        mode = "upgrade"
    max_wait = int(raw.get("max_wait_sec") or (10 if mode == "update" else 45))
    on_timeout = str(raw.get("on_timeout") or "abort").strip().lower()
    upgrade_id = str(raw.get("upgrade_id") or "").strip() or str(uuid.uuid4())
    _write_json_atomic(
        _ACTIVE_FILE,
        {
            "ok": True,
            "phase": "preparing",
            "upgrade_id": upgrade_id,
            "mode": mode,
            "started_at": _utc_now(),
        },
    )
    return {
        "upgrade_id": upgrade_id,
        "mode": mode,
        "max_wait_sec": max_wait,
        "on_timeout": on_timeout,
    }


def complete_phase(phase: str, **extra: Any) -> dict[str, Any]:
    return _update_status(phase=phase, **extra)


def fail_upgrade(error: str, detail: str = "") -> dict[str, Any]:
    lifecycle.resume()
    return _update_status(phase="failed", error=error, detail=detail)


def finish_upgrade(**extra: Any) -> dict[str, Any]:
    lifecycle.resume()
    doc = _update_status(phase="complete", **extra)
    return doc
