"""Apt upgrade signal queue + root timer integration."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fleet_server import install_channel

_SIGNAL_MAX_AGE_SEC = 300
_RESULT_NAME = "upgrade-result.json"
_REQUEST_NAME = "upgrade-request.json"


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def signal_path(data_dir: Path, channel: str) -> Path:
    if channel == "apt_system":
        return Path("/var/lib/forge-fleet") / _REQUEST_NAME
    return Path(data_dir) / _REQUEST_NAME


def result_path(data_dir: Path) -> Path:
    return Path(data_dir) / _RESULT_NAME


def timer_active() -> bool:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "forge-fleet-apt-upgrade.timer"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        return (r.stdout or "").strip() == "active"
    except (OSError, subprocess.SubprocessError):
        return False


def _package_for_channel(channel: str) -> str:
    return "forge-fleet" if channel == "apt_system" else "forge-fleet-user"


def _username_for_channel(channel: str) -> str:
    if channel == "apt_system":
        return str(os.environ.get("FLEET_SYSTEM_USER", "forge-fleet") or "forge-fleet")
    return str(os.environ.get("USER") or os.environ.get("LOGNAME") or "")


def write_upgrade_signal(
    data_dir: Path,
    *,
    mode: str,
    lifecycle_ok: bool,
    request_id: str | None = None,
) -> dict[str, Any]:
    channel = install_channel.detect_install_channel(data_dir)
    if channel not in ("apt_user", "apt_system"):
        return {
            "ok": False,
            "error": "not_apt_channel",
            "install_channel": channel,
        }
    req_id = str(request_id or "").strip() or str(uuid.uuid4())
    payload = {
        "request_id": req_id,
        "requested_at": _utc_now(),
        "mode": mode,
        "package": _package_for_channel(channel),
        "username": _username_for_channel(channel),
        "user_data_dir": str(data_dir.resolve()),
        "lifecycle_ok": bool(lifecycle_ok),
        "install_channel": channel,
    }
    path = signal_path(data_dir, channel)
    if channel == "apt_system":
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": "signal_path_unwritable", "detail": str(exc)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {
        "ok": True,
        "status": "queued",
        "request_id": req_id,
        "signal_path": str(path),
        "poll": "/v1/admin/upgrade/status",
        "eta_sec": 60,
        "timer_active": timer_active(),
    }


def read_upgrade_result(data_dir: Path) -> dict[str, Any] | None:
    path = result_path(data_dir)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def signal_stale(path: Path) -> bool:
    if not path.is_file():
        return True
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    ts = _parse_ts(str(doc.get("requested_at") or ""))
    if ts is None:
        return True
    age = datetime.now(UTC) - ts.astimezone(UTC)
    return age.total_seconds() > _SIGNAL_MAX_AGE_SEC


def queue_status(data_dir: Path) -> dict[str, Any]:
    channel = install_channel.detect_install_channel(data_dir)
    sig = signal_path(data_dir, channel)
    result = read_upgrade_result(data_dir)
    if result and result.get("ok"):
        return {"ok": True, "phase": "complete", "result": result}
    if sig.is_file() and not signal_stale(sig):
        return {"ok": True, "phase": "queued", "eta_sec": 60, "timer_active": timer_active()}
    if result and not result.get("ok"):
        return {"ok": True, "phase": "failed", "result": result}
    return {"ok": True, "phase": "idle", "timer_active": timer_active()}
