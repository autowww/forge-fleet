#!/usr/bin/env python3
"""Call a Fleet temp job. Prints status or a JSON result. Does not fetch filings."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _base() -> str:
    return os.environ.get("FORGE_FLEET_BASE_URL", "").rstrip("/")


def _token() -> str:
    return os.environ.get("FORGE_FLEET_BEARER_TOKEN", "")


def _request(method: str, path: str, body: dict | None = None) -> dict:
    base = _base()
    token = _token()
    if not base or not token:
        raise SystemExit("FORGE_FLEET_BASE_URL and FORGE_FLEET_BEARER_TOKEN are required")
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"ok": False, "error": payload[:500]}
        parsed["http"] = exc.code
        return parsed


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in {"submit", "status", "result"}:
        print("usage: fleet-temp-job.py submit|status|result ...", file=sys.stderr)
        return 2
    if argv[1] == "submit":
        recipe = argv[2] if len(argv) > 2 else "probe"
        module = argv[3] if len(argv) > 3 else ""
        body: dict = {"recipe": recipe}
        if module:
            body["module"] = module
        print(json.dumps(_request("POST", "/v1/admin/temp-jobs", body), indent=2))
        return 0
    if len(argv) < 3:
        print("job id required", file=sys.stderr)
        return 2
    path = f"/v1/admin/temp-jobs/{argv[2]}"
    if argv[1] == "result":
        path += "/result"
    print(json.dumps(_request("GET", path), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
