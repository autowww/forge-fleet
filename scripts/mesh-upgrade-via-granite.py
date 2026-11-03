#!/usr/bin/env python3
"""POST cooperative upgrade on each Granite remote peer (stash dirty trees)."""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def main() -> int:
    base = os.environ.get("FORGE_FLEET_BASE_URL", "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    token = (os.environ.get("FORGE_FLEET_BEARER_TOKEN") or "").strip()
    if not base or not token:
        print("need FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN", file=sys.stderr)
        return 2

    body = json.dumps(
        {
            "mode": "upgrade",
            "require_apt_channel": True,
            "allow_git_fallback": True,
            "stash_dirty": True,
            "max_wait_sec": 300,
            "on_timeout": "force",
        }
    ).encode()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    ctx = ssl.create_default_context()

    def get(path: str) -> dict:
        req = urllib.request.Request(base + path, headers={**headers, "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            return json.loads(resp.read().decode())

    def post(path: str) -> tuple[bool, dict]:
        req = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=300) as resp:
                payload = json.loads(resp.read().decode())
                return payload.get("ok") is True, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"ok": False, "error": raw[:200]}
            return False, payload

    peers = get("/v1/remote-peers").get("peers") or []
    ids = [str(p.get("id") or "").strip() for p in peers if isinstance(p, dict)]
    ids = [i for i in ids if i]
    if not ids:
        print("no remote peers on hub")
        return 0

    failures = 0
    for pid in ids:
        print(f"upgrade {pid}…")
        ok, payload = post(f"/v1/remote-peers/{pid}/admin/upgrade")
        print(f"  ok={ok} error={payload.get('error')} warning={payload.get('warning')}")
        if not ok:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
