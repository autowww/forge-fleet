#!/usr/bin/env python3
"""Ensure webui.forgedc.net CNAME exists for the Granite Cloudflare tunnel."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FLEET_ROOT = SCRIPT_DIR.parents[2]
KA_ENV = FLEET_ROOT.parent / "forge-knowledge-assistant" / ".env.local"
if not os.environ.get("CLOUDFLARE_API_TOKEN", "").strip() and KA_ENV.is_file():
    for line in KA_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("CLOUDFLARE_API_TOKEN="):
            os.environ["CLOUDFLARE_API_TOKEN"] = line.partition("=")[2].strip().strip("\r")
            break

token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
zone_id = os.environ.get("CF_ZONE_ID", "a930a3d1ec96b9bcaa0ab388ddad6274").strip()
tunnel_id = os.environ.get(
    "CF_TUNNEL_ID", "07ff2cbc-4741-4737-a0e5-10a60a884efd"
).strip()
hostname = os.environ.get("CF_HOSTNAME", "webui.forgedc.net").strip()
label = hostname.removesuffix(".forgedc.net").split(".")[0] if hostname.endswith(".forgedc.net") else "webui"

if not token:
    print("missing CLOUDFLARE_API_TOKEN", file=sys.stderr)
    sys.exit(2)


def api(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    listed = api(
        "GET",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?name={hostname}",
    )
    if listed.get("result"):
        print("dns_exists", hostname)
        return 0
    created = api(
        "POST",
        f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records",
        {
            "type": "CNAME",
            "name": label,
            "content": f"{tunnel_id}.cfargotunnel.com",
            "proxied": True,
        },
    )
    print("dns_create", created.get("success"), created.get("errors"))
    return 0 if created.get("success") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.HTTPError as ex:
        body = ex.read().decode("utf-8", errors="replace")
        print("http_error", ex.code, body[:400], file=sys.stderr)
        raise SystemExit(1)
