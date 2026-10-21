"""Cloudflare edge cache policy, response headers, and zone ruleset sync (stdlib)."""

from __future__ import annotations

import json
import os
import re
import stat
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fleet_server import operator_ui_settings
from fleet_server.pooled_http import pooled_request

_MAX_TTL_CAP = 86400
_RULESET_PHASE = "http_request_cache_settings"
_RULE_BYPASS_ID = "fleet_edge_cache_bypass_no_auth"
_RULE_ELIGIBLE_ID = "fleet_edge_cache_eligible_auth"

_HARD_BYPASS_PREFIXES = (
    "/v1/health",
    "/v1/version",
    "/v1/host/link-probe",
    "/v1/auth/",
    "/v1/admin/upgrade",
)

_DEFAULT_ROUTES: list[dict[str, Any]] = [
    {"method": "GET", "path": "/v1/admin/snapshot", "ttl_s": 10},
    {"method": "GET", "path": "/v1/templates", "ttl_s": 300},
    {"method": "GET", "path": "/v1/container-types", "ttl_s": 300},
    {"method": "GET", "path": "/v1/container-templates", "ttl_s": 300},
    {"method": "GET", "path": "/v1/fleet-apps/catalog", "ttl_s": 300},
    {"method": "GET", "path": "/v1/capacity", "ttl_s": 15},
    {"method": "GET", "path": "/v1/mesh/capacity", "ttl_s": 15},
    {"method": "GET", "path": "/v1/environments/telemetry", "ttl_s": 10},
]

_DEFAULT_CACHE: dict[str, Any] = {
    "enabled": False,
    "orchestrate": False,
    "max_ttl_s": 300,
    "zone_id": "",
    "routes": list(_DEFAULT_ROUTES),
    "sync": {"ok": False, "error": "", "at": 0.0},
}


def token_file(data_dir: Path) -> Path:
    return Path(data_dir) / "etc" / "cloudflare-cache.json"


def _load_token(data_dir: Path) -> str:
    path = token_file(data_dir)
    if not path.is_file():
        return ""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return ""
    if not isinstance(doc, dict):
        return ""
    return str(doc.get("api_token") or "").strip()


def save_token(data_dir: Path, api_token: str) -> None:
    tok = str(api_token or "").strip()
    if not tok:
        return
    path = token_file(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"api_token": tok}, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def token_configured(data_dir: Path) -> bool:
    return bool(_load_token(data_dir))


def merge_cache_defaults(edge: dict[str, Any]) -> dict[str, Any]:
    raw = edge.get("cache") if isinstance(edge.get("cache"), dict) else {}
    out = json.loads(json.dumps(_DEFAULT_CACHE))
    if "enabled" in raw:
        out["enabled"] = bool(raw.get("enabled"))
    if "orchestrate" in raw:
        out["orchestrate"] = bool(raw.get("orchestrate"))
    try:
        mx = int(raw.get("max_ttl_s", out["max_ttl_s"]))
        if 0 <= mx <= _MAX_TTL_CAP:
            out["max_ttl_s"] = mx
    except (TypeError, ValueError):
        pass
    if "zone_id" in raw:
        out["zone_id"] = str(raw.get("zone_id") or "").strip()
    routes = raw.get("routes")
    if isinstance(routes, list) and routes:
        cleaned: list[dict[str, Any]] = []
        for row in routes:
            if not isinstance(row, dict):
                continue
            method = str(row.get("method") or "GET").upper()
            path = str(row.get("path") or "").strip()
            if not path.startswith("/"):
                continue
            try:
                ttl = int(row.get("ttl_s", 0))
            except (TypeError, ValueError):
                ttl = 0
            if ttl < 0:
                ttl = 0
            cleaned.append({"method": method, "path": path, "ttl_s": ttl})
        if cleaned:
            out["routes"] = cleaned
    sync = raw.get("sync") if isinstance(raw.get("sync"), dict) else {}
    out["sync"] = {
        "ok": bool(sync.get("ok")),
        "error": str(sync.get("error") or "")[:500],
        "at": float(sync.get("at") or 0.0),
    }
    return out


def public_cache_view(cache: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    out = json.loads(json.dumps(cache))
    out["token_configured"] = token_configured(data_dir)
    return out


def cache_policy(data_dir: Path) -> dict[str, Any]:
    settings = operator_ui_settings.get_settings(data_dir)
    edge = settings.get("settings", {}).get("edge") or {}
    return merge_cache_defaults(edge if isinstance(edge, dict) else {})


def _policy_enabled(policy: dict[str, Any]) -> bool:
    return bool(policy.get("enabled"))


def is_hard_bypass_path(path: str) -> bool:
    bare = path.split("?", 1)[0]
    for prefix in _HARD_BYPASS_PREFIXES:
        if bare == prefix.rstrip("/") or bare.startswith(prefix):
            return True
    return False


def clamp_ttl(requested: int, policy: dict[str, Any]) -> int:
    try:
        req = int(requested)
    except (TypeError, ValueError):
        req = 0
    if req <= 0:
        return 0
    try:
        cap = int(policy.get("max_ttl_s") or _DEFAULT_CACHE["max_ttl_s"])
    except (TypeError, ValueError):
        cap = 300
    cap = min(max(cap, 0), _MAX_TTL_CAP)
    return min(req, cap)


def _route_match(method: str, path: str, policy: dict[str, Any]) -> int:
    bare = path.split("?", 1)[0]
    m = method.upper()
    for row in policy.get("routes") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("method") or "GET").upper() != m:
            continue
        route_path = str(row.get("path") or "")
        if bare == route_path or bare.startswith(route_path.rstrip("/") + "/"):
            try:
                return int(row.get("ttl_s") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def resolve_ttl(
    *,
    method: str,
    path: str,
    status: int,
    data_dir: Path,
    app_requested_ttl: int | None = None,
) -> int:
    if method.upper() != "GET" or status != 200:
        return 0
    if is_hard_bypass_path(path):
        return 0
    policy = cache_policy(data_dir)
    if not _policy_enabled(policy):
        return 0
    route_ttl = _route_match(method, path, policy)
    requested = app_requested_ttl if app_requested_ttl is not None else route_ttl
    if requested is None or requested <= 0:
        return 0
    return clamp_ttl(requested, policy)


def _cache_tag(path: str) -> str:
    bare = path.split("?", 1)[0].strip("/").replace("/", "-")
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", bare)[:80] or "root"
    return f"fleet-{safe}"


def merge_vary(headers: dict[str, str], *extra: str) -> None:
    existing = headers.get("Vary") or headers.get("vary") or ""
    parts = [p.strip() for p in existing.split(",") if p.strip()]
    lower = {p.lower() for p in parts}
    for name in extra:
        if name.lower() not in lower:
            parts.append(name)
            lower.add(name.lower())
    if parts:
        headers["Vary"] = ", ".join(parts)


def apply_response_cache_headers(headers: dict[str, str], ttl: int, path: str) -> None:
    headers["Cache-Control"] = "private, no-store"
    if ttl <= 0:
        headers.pop("Cloudflare-CDN-Cache-Control", None)
        headers.pop("Cache-Tag", None)
        return
    headers["Cloudflare-CDN-Cache-Control"] = f"public, max-age={ttl}"
    headers["Cache-Tag"] = _cache_tag(path)
    merge_vary(headers, "Authorization")


def _normalize_gateway_paths(paths: Any) -> list[str]:
    if not isinstance(paths, list):
        return []
    out: list[str] = []
    for raw in paths:
        p = str(raw or "").strip().lstrip("/")
        if not p or ".." in p.split("/"):
            continue
        out.append(p)
    return out


def _gateway_path_matches(rest_path: str, paths: list[str]) -> bool:
    rest = str(rest_path or "").lstrip("/")
    if not paths:
        return True
    for prefix in paths:
        if rest == prefix or rest.startswith(prefix.rstrip("/") + "/"):
            return True
    return False


def _path_has_traversal(raw: str) -> bool:
    return ".." in str(raw or "").split("/")


def _validate_gateway_path_prefixes(
    service_id: str, path_prefixes: list[str]
) -> dict[str, Any] | None:
    from fleet_server import app_gateway

    public_prefix = app_gateway.public_path(service_id)
    for p in path_prefixes:
        full = f"{public_prefix}/{p}".split("?", 1)[0]
        if is_hard_bypass_path(full) or is_hard_bypass_path("/" + p.lstrip("/")):
            return {"ok": False, "error": "path_not_allowed", "detail": full[:200]}
    return None


def _normalize_gateway_routes(
    raw_routes: Any, *, policy: dict[str, Any], fallback_ttl: int
) -> list[dict[str, Any]] | None:
    if not isinstance(raw_routes, list) or not raw_routes:
        return None
    out: list[dict[str, Any]] = []
    for row in raw_routes:
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip().lstrip("/")
        if not path or _path_has_traversal(path):
            return None
        try:
            ttl = int(row.get("ttl_s", fallback_ttl))
        except (TypeError, ValueError):
            ttl = fallback_ttl
        out.append({"path": path, "ttl_s": clamp_ttl(ttl, policy)})
    return out if out else None


def _longest_prefix_route_ttl(rest_path: str, routes: list[dict[str, Any]]) -> int | None:
    rest = str(rest_path or "").lstrip("/")
    best_len = -1
    best_ttl: int | None = None
    for row in routes:
        prefix = str(row.get("path") or "").strip().lstrip("/")
        if not prefix:
            continue
        if rest == prefix or rest.startswith(prefix.rstrip("/") + "/"):
            if len(prefix) > best_len:
                best_len = len(prefix)
                try:
                    best_ttl = int(row.get("ttl_s") or 0)
                except (TypeError, ValueError):
                    best_ttl = 0
    return best_ttl


def resolve_gateway_proxy_ttl(
    *,
    method: str,
    rest_path: str,
    status: int,
    gateway_record: dict[str, Any],
    data_dir: Path,
) -> int:
    if method.upper() != "GET" or status != 200:
        return 0
    edge_cache = gateway_record.get("edge_cache")
    if not isinstance(edge_cache, dict):
        return 0
    policy = cache_policy(data_dir)
    if not _policy_enabled(policy):
        return 0
    routes = edge_cache.get("routes")
    if isinstance(routes, list) and routes:
        requested = _longest_prefix_route_ttl(rest_path, routes)
        if requested is None:
            return 0
        return clamp_ttl(requested, policy)
    paths = _normalize_gateway_paths(edge_cache.get("paths"))
    if not _gateway_path_matches(rest_path, paths):
        return 0
    try:
        requested = int(edge_cache.get("ttl_s") or 0)
    except (TypeError, ValueError):
        return 0
    return clamp_ttl(requested, policy)


def register_gateway_edge_cache(
    data_dir: Path,
    service_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    from fleet_server import app_gateway

    rec = app_gateway.load_gateway(data_dir, service_id)
    if rec is None:
        return {"ok": False, "error": "gateway_not_found"}
    policy = cache_policy(data_dir)
    fallback_ttl = 0
    if "ttl_s" in body:
        try:
            fallback_ttl = clamp_ttl(int(body.get("ttl_s", 0)), policy)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid_ttl_s"}
    raw_paths = body.get("paths")
    if isinstance(raw_paths, list):
        for raw in raw_paths:
            if _path_has_traversal(str(raw or "")):
                return {"ok": False, "error": "invalid_path"}
    routes = _normalize_gateway_routes(body.get("routes"), policy=policy, fallback_ttl=fallback_ttl)
    if body.get("routes") is not None and routes is None:
        return {"ok": False, "error": "invalid_routes"}
    paths = _normalize_gateway_paths(body.get("paths"))
    path_prefixes = [str(r["path"]) for r in routes] if routes else paths
    denied = _validate_gateway_path_prefixes(service_id, path_prefixes)
    if denied:
        return denied
    if routes:
        edge_cache_doc: dict[str, Any] = {
            "routes": routes,
            "paths": [r["path"] for r in routes],
            "updated_at": time.time(),
        }
        if fallback_ttl > 0:
            edge_cache_doc["ttl_s"] = fallback_ttl
    else:
        ttl_s = fallback_ttl
        edge_cache_doc = {"ttl_s": ttl_s, "paths": paths, "updated_at": time.time()}
    rec["edge_cache"] = edge_cache_doc
    app_gateway.save_gateway_record(data_dir, rec)
    sync = schedule_cloudflare_sync(data_dir)
    return {"ok": True, "edge_cache": edge_cache_doc, "sync": sync}


def _public_hostname(data_dir: Path) -> str:
    settings = operator_ui_settings.get_settings(data_dir)
    edge = settings.get("settings", {}).get("edge") or {}
    host = str(edge.get("public_hostname") or "").strip()
    if host.startswith("http://") or host.startswith("https://"):
        try:
            host = urlparse(host).hostname or host
        except Exception:
            pass
    return host


def _record_sync(data_dir: Path, sync: dict[str, Any]) -> None:
    operator_ui_settings.update_cache_sync(data_dir, sync)


def maybe_sync_cloudflare(data_dir: Path) -> dict[str, Any]:
    policy = cache_policy(data_dir)
    if not policy.get("orchestrate"):
        return {"ok": False, "error": "not_orchestrator", "at": time.time()}
    return sync_zone_cache_rules(data_dir)


def schedule_cloudflare_sync(data_dir: Path) -> dict[str, Any]:
    """Queue zone ruleset sync on a daemon thread so HTTP handlers return promptly."""
    policy = cache_policy(data_dir)
    if not policy.get("orchestrate"):
        return {"ok": False, "error": "not_orchestrator", "at": time.time()}

    def _run() -> None:
        try:
            sync_zone_cache_rules(data_dir)
        except Exception:
            _record_sync(
                data_dir,
                {"ok": False, "error": "sync_failed", "at": time.time()},
            )

    threading.Thread(target=_run, name="fleet-edge-cache-sync", daemon=True).start()
    return {"ok": True, "error": "", "at": time.time(), "pending": True}


def sync_zone_cache_rules(data_dir: Path) -> dict[str, Any]:
    policy = cache_policy(data_dir)
    if not policy.get("orchestrate"):
        out = {"ok": False, "error": "not_orchestrator", "at": time.time()}
        _record_sync(data_dir, out)
        return out
    zone_id = str(policy.get("zone_id") or "").strip()
    token = _load_token(data_dir)
    host = _public_hostname(data_dir)
    if not zone_id:
        out = {"ok": False, "error": "zone_id_missing", "at": time.time()}
        _record_sync(data_dir, out)
        return out
    if not token:
        out = {"ok": False, "error": "token_missing", "at": time.time()}
        _record_sync(data_dir, out)
        return out
    if not host:
        out = {"ok": False, "error": "public_hostname_missing", "at": time.time()}
        _record_sync(data_dir, out)
        return out
    try:
        body = _ruleset_body(host, enabled=bool(policy.get("enabled")))
        _upsert_zone_ruleset(zone_id, token, body)
    except CloudflareSyncError as exc:
        out = {"ok": False, "error": str(exc)[:500], "at": time.time()}
        _record_sync(data_dir, out)
        return out
    out = {"ok": True, "error": "", "at": time.time()}
    _record_sync(data_dir, out)
    return out


class CloudflareSyncError(RuntimeError):
    pass


def _ruleset_body(hostname: str, *, enabled: bool) -> dict[str, Any]:
    host_expr = f'http.host eq "{hostname}"'
    get_expr = f"({host_expr} and http.request.method eq \"GET\")"
    if not enabled:
        return {
            "rules": [
                {
                    "action": "set_cache_settings",
                    "description": _RULE_BYPASS_ID,
                    "expression": get_expr,
                    "enabled": True,
                    "action_parameters": {"cache": False},
                }
            ]
        }
    # App-gateway only. Caddy replaces Authorization before Fleet, and this zone
    # cannot set a custom cache key, so do not cache /v1/admin or other client-bearer routes.
    gateway_expr = (
        f"({get_expr} and starts_with(http.request.uri.path, \"/v1/app-gateways/\"))"
    )
    return {
        "rules": [
            {
                "action": "set_cache_settings",
                "description": _RULE_ELIGIBLE_ID,
                "expression": gateway_expr,
                "enabled": True,
                "action_parameters": {
                    "cache": True,
                    "edge_ttl": {"mode": "respect_origin"},
                },
            },
        ]
    }


def _cf_request(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    status, resp_headers, raw = pooled_request(method, url, headers=headers, body=payload, timeout=45.0)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CloudflareSyncError(f"cloudflare_invalid_json status={status}") from None
    if not isinstance(doc, dict):
        raise CloudflareSyncError(f"cloudflare_bad_payload status={status}")
    if status >= 400 or not doc.get("success"):
        errs = doc.get("errors")
        detail = ""
        if isinstance(errs, list) and errs:
            detail = str(errs[0].get("message") or errs[0])[:300]
        raise CloudflareSyncError(detail or f"cloudflare_http_{status}")
    return doc


def _upsert_zone_ruleset(zone_id: str, token: str, ruleset: dict[str, Any]) -> None:
    base = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/rulesets"
    entry_url = f"{base}/phases/{_RULESET_PHASE}/entrypoint"
    result: dict[str, Any] | None = None
    try:
        doc = _cf_request("GET", entry_url, token)
        raw = doc.get("result")
        if isinstance(raw, dict):
            result = raw
    except CloudflareSyncError:
        result = None
    if result and result.get("id"):
        ruleset_id = str(result["id"])
        put_url = f"{base}/{ruleset_id}"
        _cf_request("PUT", put_url, token, {"rules": ruleset.get("rules") or []})
        return
    _cf_request(
        "POST",
        base,
        token,
        {
            "name": "Fleet edge cache",
            "kind": "zone",
            "phase": _RULESET_PHASE,
            "rules": ruleset.get("rules") or [],
        },
    )


def list_gateway_edge_registrations(data_dir: Path) -> list[dict[str, Any]]:
    from fleet_server import app_gateway

    out: list[dict[str, Any]] = []
    for rec in app_gateway.list_gateways(data_dir):
        sid = str(rec.get("service_id") or "")
        full = app_gateway.load_gateway(data_dir, sid)
        if not full:
            continue
        ec = full.get("edge_cache")
        if isinstance(ec, dict) and ec:
            out.append({"service_id": sid, "edge_cache": ec})
    return out
