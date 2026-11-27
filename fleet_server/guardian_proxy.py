"""Forward /v1/admin/guardian* to the local fleet-guardian process."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

_FINDING = re.compile(r"^/v1/admin/guardian/findings/([^/]+)/decision$")


def local_base() -> str:
    return str(os.environ.get("FLEET_GUARDIAN_URL") or "http://127.0.0.1:18780").rstrip("/")


def upstream_path(path: str) -> str | None:
    if path in {
        "/v1/admin/guardian",
        "/v1/admin/guardian/digest",
        "/v1/admin/guardian/digest/ack",
        "/v1/admin/guardian/fixtures",
    }:
        return path.replace("/v1/admin/guardian", "/v1/guardian", 1)
    match = _FINDING.match(path)
    if match:
        return f"/v1/guardian/findings/{match.group(1)}/decision"
    return None


def forward(method: str, path: str, body: bytes | None, timeout_s: float = 8.0) -> tuple[int, bytes, str]:
    upstream = upstream_path(path)
    if upstream is None:
        raw = json.dumps({"ok": False, "error": "not_found"}).encode("utf-8")
        return 404, raw, "application/json"
    req = urllib.request.Request(local_base() + upstream, data=body, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type") or "application/json"
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), "application/json"
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raw = json.dumps({"ok": False, "error": "guardian_unreachable", "detail": str(exc)[:200]}).encode("utf-8")
        return 503, raw, "application/json"
