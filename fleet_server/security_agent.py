"""Matrix security agent: alerts and operator reply commands."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fleet_server import request_guard, security_store

_AGENT_STARTED = False
_LAST_ALERT_TS = 0.0
_MUTED_UNTIL = 0.0


def _matrix_cfg() -> dict[str, str]:
    return {
        "homeserver": str(os.environ.get("FLEET_SECURITY_MATRIX_HOMESERVER") or "").rstrip("/"),
        "room": str(os.environ.get("FLEET_SECURITY_MATRIX_ROOM") or "").strip(),
        "token": str(os.environ.get("FLEET_SECURITY_MATRIX_ACCESS_TOKEN") or "").strip(),
    }


def status_payload(db_path: Path | str | None = None) -> dict[str, Any]:
    cfg = _matrix_cfg()
    siege = False
    if db_path is not None:
        siege = bool(request_guard.blocks_payload(db_path).get("siege_active"))
    return {
        "ok": True,
        "enabled": bool(cfg["homeserver"] and cfg["room"] and cfg["token"]),
        "room": cfg["room"] or None,
        "muted_until": _MUTED_UNTIL if _MUTED_UNTIL > time.time() else None,
        "guard_mode": request_guard.guard_mode(),
        "siege_active": siege,
    }


def _send_matrix(body: str) -> dict[str, Any]:
    cfg = _matrix_cfg()
    if not (cfg["homeserver"] and cfg["room"] and cfg["token"]):
        return {"ok": False, "error": "matrix_not_configured"}
    txn = f"fleet-{int(time.time() * 1000)}"
    url = f"{cfg['homeserver']}/_matrix/client/v3/rooms/{cfg['room']}/send/m.room.message/{txn}"
    payload = json.dumps({"msgtype": "m.text", "body": body}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {cfg['token']}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
    except (urllib.error.URLError, OSError, TimeoutError) as ex:
        return {"ok": False, "error": str(ex)[:300]}
    return {"ok": True}


def send_test_alert() -> dict[str, Any]:
    return _send_matrix("Fleet security agent test — ignore.")


def _poll_alerts(db_path: Path) -> None:
    global _LAST_ALERT_TS, _MUTED_UNTIL
    from fleet_server import store

    cfg = _matrix_cfg()
    if not (cfg["homeserver"] and cfg["room"] and cfg["token"]):
        return
    now = time.time()
    if now < _MUTED_UNTIL:
        return
    conn = store.connect(db_path)
    try:
        events = security_store.list_events(conn, _LAST_ALERT_TS or now - 120, limit=50)
    finally:
        conn.close()
    critical = [e for e in events if str(e.get("severity") or "") in {"critical", "high"}]
    if not critical:
        return
    _LAST_ALERT_TS = max(float(e.get("ts") or 0) for e in critical)
    lines = ["Fleet security alert"]
    for e in critical[:5]:
        lines.append(
            f"- {e.get('severity')}: {e.get('rule')} {e.get('method')} {e.get('path')} from {e.get('source')}"
        )
    lines.append("Reply: unblock <source> | confirm <id> | mute 1h")
    _send_matrix("\n".join(lines))


def _poll_commands(db_path: Path, data_dir: Path) -> None:
    global _MUTED_UNTIL
    cfg = _matrix_cfg()
    if not (cfg["homeserver"] and cfg["room"] and cfg["token"]):
        return
    url = (
        f"{cfg['homeserver']}/_matrix/client/v3/rooms/{cfg['room']}/messages"
        f"?dir=b&limit=10"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {cfg['token']}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
        return
    from fleet_server import store

    for ev in doc.get("chunk") or []:
        if ev.get("type") != "m.room.message":
            continue
        body = str((ev.get("content") or {}).get("body") or "").strip()
        if body.startswith("unblock "):
            src = body.split(" ", 1)[1].strip()
            conn = store.connect(db_path)
            try:
                security_store.remove_block(conn, src)
            finally:
                conn.close()
            _send_matrix(f"Unblocked {src}")
        elif body.startswith("mute "):
            part = body.split(" ", 1)[1].strip().lower()
            if part.endswith("h"):
                try:
                    hours = float(part[:-1])
                    _MUTED_UNTIL = time.time() + hours * 3600
                except ValueError:
                    pass


def start_agent(db_path: Path, data_dir: Path) -> None:
    global _AGENT_STARTED
    if _AGENT_STARTED:
        return
    _AGENT_STARTED = True
    cfg = _matrix_cfg()
    if not (cfg["homeserver"] and cfg["room"] and cfg["token"]):
        return

    def _loop() -> None:
        while True:
            time.sleep(45)
            try:
                _poll_alerts(db_path)
                _poll_commands(db_path, data_dir)
            except Exception:
                pass

    threading.Thread(target=_loop, name="fleet-security-agent", daemon=True).start()
