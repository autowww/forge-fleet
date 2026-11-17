"""Local Fleet presence heartbeat. Copy this file into a product. It only calls 127.0.0.1."""

from __future__ import annotations

import json
import os
import threading
import urllib.request


def _local_heartbeat_url(port: str) -> str:
    """Only the Fleet on this machine. Containers may use host.docker.internal."""
    fallback = f"http://127.0.0.1:{port}/v1/presence/heartbeat"
    raw = os.environ.get("FLEET_PRESENCE_URL", "").strip().rstrip("/")
    if not raw:
        return fallback
    host = raw.split("://", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    if host not in {"127.0.0.1", "localhost", "host.docker.internal"}:
        return fallback
    return raw + "/v1/presence/heartbeat"


def start(
    *,
    instance_id: str,
    kind: str,
    purpose: str,
    label: str,
    auth: str,
    status: str = "running",
    detail: str = "",
    interval_s: float = 15.0,
    port: str | None = None,
) -> threading.Thread:
    listen = (port or os.environ.get("FLEET_PORT") or "18766").strip()
    url = _local_heartbeat_url(listen)
    token = (
        os.environ.get("FLEET_BEARER_TOKEN")
        or os.environ.get("FORGE_FLEET_BEARER_TOKEN")
        or os.environ.get("FLEET_WAKE_BEARER_TOKEN")
        or ""
    ).strip()
    body = {
        "id": instance_id,
        "k": kind,
        "p": purpose,
        "l": label,
        "s": status,
        "a": auth,
        "d": detail,
        "ttl": 45,
    }
    payload = json.dumps(body, separators=(",", ":")).encode("utf-8")

    def _loop() -> None:
        import time

        while True:
            try:
                req = urllib.request.Request(url, data=payload, method="POST")
                req.add_header("Content-Type", "application/json")
                if token:
                    req.add_header("Authorization", "Bearer " + token)
                urllib.request.urlopen(req, timeout=2).read()
            except Exception:
                pass
            time.sleep(interval_s)

    thread = threading.Thread(target=_loop, name=f"presence-{instance_id}", daemon=True)
    thread.start()
    return thread
