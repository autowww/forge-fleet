#!/usr/bin/env python3
"""Cooperative Fleet upgrade: local console, direct peers, and hub-managed peers."""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

UPGRADE_BODY = json.dumps(
    {
        "mode": "upgrade",
        "require_apt_channel": True,
        "allow_git_fallback": True,
        "max_wait_sec": 120,
        "on_timeout": "abort",
    }
).encode()


def _request(
    base: str,
    path: str,
    *,
    bearer: str | None,
    method: str = "GET",
    body: bytes | None = None,
) -> tuple[int, dict | None, str]:
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=240) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                payload = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                payload = None
            return resp.status, payload if isinstance(payload, dict) else None, raw[:400]
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            payload = None
        return exc.code, payload if isinstance(payload, dict) else None, raw[:400]


def post_upgrade(base: str, path: str, bearer: str | None) -> tuple[bool, str]:
    code, payload, snippet = _request(base, path, bearer=bearer, method="POST", body=UPGRADE_BODY)
    ok = payload.get("ok") is True if isinstance(payload, dict) else 200 <= code < 300
    detail = ""
    if isinstance(payload, dict):
        detail = str(payload.get("warning") or payload.get("error") or payload.get("note") or "")
    if not detail:
        detail = snippet
    return ok, f"HTTP {code}" + (f" · {detail}" if detail else "")


def main() -> int:
    local = os.environ.get("FLEET_LOCAL_URL", "http://127.0.0.1:18766").rstrip("/")
    local_bearer = (os.environ.get("FLEET_LOCAL_BEARER") or "").strip() or None
    data_dir = Path(os.environ.get("FLEET_DATA_DIR", Path.home() / ".local/state/forge-fleet"))
    peers_file = data_dir / "etc" / "remote-peers.json"

    failures = 0

    print(f"[mesh-upgrade] local {local}")
    ok, msg = post_upgrade(local, "/v1/admin/upgrade", local_bearer)
    print(f"  -> {'ok' if ok else 'FAIL'} {msg}")
    if not ok:
        failures += 1

    hubs: list[dict] = []
    if peers_file.is_file():
        try:
            doc = json.loads(peers_file.read_text(encoding="utf-8"))
            hubs = [p for p in doc.get("peers") or [] if isinstance(p, dict)]
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[mesh-upgrade] WARN: could not read {peers_file}: {exc}", file=sys.stderr)

    for hub in hubs:
        hub_id = str(hub.get("id") or "").strip()
        hub_base = str(hub.get("base_url") or "").rstrip("/")
        hub_token = str(hub.get("bearer_token") or "").strip() or None
        if not hub_id or not hub_base:
            continue

        proxy_path = f"/v1/remote-peers/{hub_id}/admin/upgrade"
        print(f"[mesh-upgrade] direct peer {hub_id} via local proxy")
        ok, msg = post_upgrade(local, proxy_path, local_bearer)
        print(f"  -> {'ok' if ok else 'FAIL'} {msg}")
        if not ok:
            failures += 1

        if not hub_token:
            print(f"[mesh-upgrade] skip hub children for {hub_id} (no bearer in {peers_file})")
            continue

        code, listing, _ = _request(hub_base, "/v1/remote-peers", bearer=hub_token)
        if code != 200 or not isinstance(listing, dict):
            print(f"[mesh-upgrade] WARN: could not list peers on {hub_id} (HTTP {code})")
            failures += 1
            continue
        children = [c for c in listing.get("peers") or [] if isinstance(c, dict)]
        if not children:
            print(f"[mesh-upgrade] hub {hub_id}: no remote peers configured")
            continue
        for child in children:
            child_id = str(child.get("id") or "").strip()
            if not child_id:
                continue
            child_path = f"/v1/remote-peers/{child_id}/admin/upgrade"
            label = str(child.get("label") or child_id)
            print(f"[mesh-upgrade] hub {hub_id} -> {label} ({child_id})")
            ok, msg = post_upgrade(hub_base, child_path, hub_token)
            print(f"  -> {'ok' if ok else 'FAIL'} {msg}")
            if not ok:
                failures += 1

    print(f"[mesh-upgrade] finished with {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
