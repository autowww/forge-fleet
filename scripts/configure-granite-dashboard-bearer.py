#!/usr/bin/env python3
"""Store dashboard bearer + operator settings on Granite (Fleet API)."""
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

    hostname = (os.environ.get("FLEET_PUBLIC_HOSTNAME") or "granite.forgedc.net").strip()
    git_root = (os.environ.get("FLEET_GIT_ROOT") or "/home/administrator/forge-fleet").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    ctx = ssl.create_default_context()

    def req(method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(r, context=ctx, timeout=120) as resp:
            return json.loads(resp.read().decode())

    req(
        "PUT",
        "/v1/operator/dashboard-browser-bearer",
        {"bearer_token": token},
    )
    req(
        "PUT",
        "/v1/operator/ui-settings",
        {
            "setup_completed": True,
            "machine_role": "server",
            "edge": {
                "public_hostname": hostname,
                "forge_fleet_checkout": git_root,
                "layout": "user",
                "caddy_verified": True,
            },
        },
    )
    print("configured dashboard bearer file and operator ui-settings on", base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
