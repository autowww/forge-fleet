"""Generic Fleet app gateway — proxy migrated app HTTP via the existing Fleet API.

Recipes register a loopback upstream. Clients keep using the Fleet hostname and
Fleet bearer; Fleet injects the app bearer when the upstream requires one.

A new Cloudflare tunnel is not created. Public routing stays on the Fleet edge
(``https://<fleet-host>/v1/app-gateways/<service_id>/…``).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

_SERVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
_FORWARD_REQ_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "x-forge-role",
    "x-forge-actor",
}
_MAX_PROXY_BODY = 64 * 1024 * 1024
_PROXY_TIMEOUT_S = 60.0
_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5179",
    "http://localhost:5179",
    "http://127.0.0.1:4179",
    "http://localhost:4179",
)


def _meta_str(meta: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = str(meta.get(key) or "").strip()
        if val:
            return val
    return ""


def _meta_bool(meta: dict[str, Any], *keys: str, default: bool = False) -> bool:
    for key in keys:
        raw = meta.get(key)
        if raw is None:
            continue
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return default


def gateways_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "etc" / "app-gateways"


def _gateway_path(data_dir: Path, service_id: str) -> Path:
    return gateways_dir(data_dir) / f"{service_id}.json"


def validate_service_id(service_id: str) -> str:
    sid = str(service_id or "").strip().lower()
    if not _SERVICE_ID_RE.match(sid):
        raise ValueError("gateway service_id must be a lowercase slug (letters, digits, hyphen)")
    return sid


def validate_loopback_upstream(url: str) -> str:
    raw = str(url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("gateway_upstream must be an http(s) URL")
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        raise ValueError("gateway_upstream must be loopback (127.0.0.1 / localhost); use the Fleet API as the public edge")
    if parsed.path not in {"", "/"}:
        raise ValueError("gateway_upstream must be an origin (no path)")
    return raw


def public_path(service_id: str) -> str:
    return f"/v1/app-gateways/{validate_service_id(service_id)}"


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    out = {
        "service_id": record.get("service_id"),
        "upstream": record.get("upstream"),
        "path": public_path(str(record.get("service_id") or "")),
        "inject_bearer": bool(record.get("inject_bearer")),
        "bearer_configured": bool(str(record.get("upstream_bearer") or "").strip()),
        "app_bearer_env": record.get("app_bearer_env") or "",
        "host_ui": bool(record.get("host_ui")),
        "updated_at": record.get("updated_at") or "",
        "via": "fleet_api",
    }
    return out


def load_gateway(data_dir: Path, service_id: str) -> dict[str, Any] | None:
    path = _gateway_path(data_dir, validate_service_id(service_id))
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    return doc if isinstance(doc, dict) else None


def list_gateways(data_dir: Path) -> list[dict[str, Any]]:
    root = gateways_dir(data_dir)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json")):
        rec = load_gateway(data_dir, path.stem)
        if rec:
            out.append(public_record(rec))
    return out


def save_gateway(data_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    sid = validate_service_id(str(record.get("service_id") or ""))
    upstream = validate_loopback_upstream(str(record.get("upstream") or ""))
    root = gateways_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = _gateway_path(data_dir, sid)
    payload = {
        "service_id": sid,
        "upstream": upstream,
        "inject_bearer": bool(record.get("inject_bearer", True)),
        "upstream_bearer": str(record.get("upstream_bearer") or "").strip(),
        "app_bearer_env": str(record.get("app_bearer_env") or "").strip(),
        "host_ui": bool(record.get("host_ui")),
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "via": "fleet_api",
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return payload


def upsert_dotenv(path: Path, key: str, value: str) -> None:
    token_key = str(key or "").strip()
    if not token_key or not token_key.replace("_", "").isalnum():
        raise ValueError("invalid dotenv key")
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    out: list[str] = []
    prefix = f"{token_key}="
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix) or stripped.startswith(f"export {prefix}"):
            out.append(f"{token_key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{token_key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def read_dotenv_value(path: Path, key: str) -> str:
    if not path.is_file():
        return ""
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip().strip('"').strip("'")
    return ""


def prepare_compose_app_bearer(meta: dict[str, Any]) -> dict[str, Any]:
    """Generate and persist an app API token in compose ``.env`` when required and empty."""
    env_name = _meta_str(meta, "app_bearer_env", "app_bearer_env")
    if not env_name:
        return {"skipped": True, "generated": False, "token_set": False}
    from fleet_server.migration_jobs import _resolve_compose_root

    compose_root = _resolve_compose_root(meta)
    if compose_root is None:
        raise ValueError("app_bearer_env is set but compose_root is missing")
    env_path = compose_root / ".env"
    existing = read_dotenv_value(env_path, env_name)
    if existing:
        return {"skipped": False, "generated": False, "token_set": True, "env_name": env_name}
    token = secrets.token_urlsafe(32)
    upsert_dotenv(env_path, env_name, token)
    return {"skipped": False, "generated": True, "token_set": True, "env_name": env_name}


def apply_compose_env(meta: dict[str, Any]) -> dict[str, Any]:
    """Write recipe-supplied ``compose_env`` keys into compose ``.env`` (product-agnostic)."""
    extra = meta.get("compose_env")
    if not isinstance(extra, dict) or not extra:
        return {"skipped": True, "keys": []}
    from fleet_server.migration_jobs import _resolve_compose_root

    compose_root = _resolve_compose_root(meta)
    if compose_root is None:
        raise ValueError("compose_env is set but compose_root is missing")
    env_path = compose_root / ".env"
    written: list[str] = []
    for raw_key, raw_val in extra.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        upsert_dotenv(env_path, key, str(raw_val))
        written.append(key)
    return {"skipped": False, "keys": written}


def register_from_migration_meta(data_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """Register a Fleet API gateway from recipe/migration meta (no new tunnel)."""
    prefer_fleet = _meta_bool(meta, "prefer_fleet_gateway", "prefer_fleet_gateway", default=True)
    create_host = _meta_bool(meta, "create_public_hostname", "create_cloudflare_tunnel", default=False)
    if create_host and not prefer_fleet:
        raise ValueError(
            "new Cloudflare tunnels are disabled; expose the app through the existing Fleet API "
            "(/v1/app-gateways/<service_id>/)"
        )
    service_id = _meta_str(meta, "gateway_service_id", "gateway_service_id", "service_id")
    upstream = _meta_str(meta, "gateway_upstream", "gateway_upstream")
    if not service_id:
        raise ValueError("register_edge_route requires meta.gateway_service_id or meta.service_id")
    if not upstream:
        raise ValueError(
            "register_edge_route requires meta.gateway_upstream (loopback http URL). "
            "Fleet gateways the app on the existing Fleet hostname instead of a new tunnel."
        )
    prep = prepare_compose_app_bearer(meta)
    env_name = _meta_str(meta, "app_bearer_env", "app_bearer_env")
    bearer = ""
    from fleet_server.migration_jobs import _resolve_compose_root

    compose_root = _resolve_compose_root(meta)
    if env_name and compose_root is not None:
        bearer = read_dotenv_value(compose_root / ".env", env_name)
    record = save_gateway(
        data_dir,
        {
            "service_id": service_id,
            "upstream": upstream,
            "inject_bearer": bool(env_name),
            "upstream_bearer": bearer,
            "app_bearer_env": env_name,
            "host_ui": _meta_bool(meta, "host_ui", "host_ui", default=False),
        },
    )
    public = public_record(record)
    public["bearer_generated"] = bool(prep.get("generated"))
    public["new_tunnel"] = False
    return public


def cors_origin_allowed(origin: str) -> str:
    raw = str(origin or "").strip()
    extra = {
        part.strip()
        for part in str(os.environ.get("FLEET_APP_GATEWAY_CORS_ORIGINS") or "").split(",")
        if part.strip()
    }
    allowed = set(_DEFAULT_CORS_ORIGINS) | extra
    return raw if raw in allowed else ""


def apply_cors(headers: dict[str, str], req_headers: Any) -> None:
    origin = cors_origin_allowed(
        str(req_headers.get("Origin") or req_headers.get("origin") or "")
    )
    if not origin:
        return
    headers["Access-Control-Allow-Origin"] = origin
    headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, X-Forge-Role, X-Forge-Actor"
    )
    headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    headers["Vary"] = "Origin"


def delete_gateway(data_dir: Path, service_id: str) -> bool:
    path = _gateway_path(data_dir, validate_service_id(service_id))
    if not path.is_file():
        return False
    path.unlink()
    return True


def _rewrite_rooted_urls(body: bytes, prefix: str) -> bytes:
    """Prefix root-relative URLs so HTML/JS/CSS work under /v1/app-gateways/<id>/."""
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    skip = re.escape(prefix.lstrip("/")).encode("ascii")
    pattern = re.compile(rb'(["\'(=])/(?!/|' + skip + rb")")
    return pattern.sub(rb"\1" + prefix.encode("ascii") + b"/", body)


def _inject_html_prefix(body: bytes, content_type: str, prefix: str) -> bytes:
    ctype = content_type.lower()
    if any(token in ctype for token in ("html", "javascript", "ecmascript", "css")):
        body = _rewrite_rooted_urls(body, prefix)
    if "html" not in ctype:
        return body
    marker = b"window.__FORGE_API_BASE__"
    if marker in body:
        return body
    snippet = (
        f'<script>window.__FORGE_API_BASE__={json.dumps(prefix)};</script>'
    ).encode("utf-8")
    lower = body.lower()
    idx = lower.find(b"<head")
    if idx >= 0:
        gt = body.find(b">", idx)
        if gt >= 0:
            return body[: gt + 1] + snippet + body[gt + 1 :]
    return snippet + body


def proxy(
    record: dict[str, Any],
    *,
    method: str,
    rest_path: str,
    query: str,
    req_headers: Any,
    body: bytes,
) -> tuple[int, dict[str, str], bytes]:
    upstream = str(record.get("upstream") or "").rstrip("/")
    rest = str(rest_path or "").lstrip("/")
    target = f"{upstream}/{rest}" if rest else f"{upstream}/"
    if query:
        target = f"{target}?{query}"
    headers: dict[str, str] = {}
    for key in _FORWARD_REQ_HEADERS:
        val = str(req_headers.get(key) or req_headers.get(key.title()) or "").strip()
        if val:
            headers[key.title() if "-" in key else key] = val
    bearer = str(record.get("upstream_bearer") or "").strip()
    if bearer and record.get("inject_bearer", True):
        headers["Authorization"] = f"Bearer {bearer}"
    req = Request(target, data=body if body else None, method=str(method).upper(), headers=headers)
    try:
        with urlopen(req, timeout=_PROXY_TIMEOUT_S) as resp:
            payload = resp.read(_MAX_PROXY_BODY)
            status = int(getattr(resp, "status", 200) or 200)
            raw_headers = dict(resp.headers.items()) if resp.headers else {}
    except HTTPError as exc:
        payload = exc.read(_MAX_PROXY_BODY) if exc.fp else b""
        status = int(exc.code)
        raw_headers = dict(exc.headers.items()) if exc.headers else {}
    except URLError as exc:
        err_headers = {"Content-Type": "application/json"}
        apply_cors(err_headers, req_headers)
        return 502, err_headers, json.dumps(
            {"ok": False, "error": "upstream_unreachable", "detail": str(exc.reason)[:400]}
        ).encode("utf-8")
    out_headers: dict[str, str] = {}
    for key, val in raw_headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        out_headers[key] = val
    ctype = out_headers.get("Content-Type") or out_headers.get("content-type") or "application/octet-stream"
    prefix = public_path(str(record.get("service_id") or ""))
    if record.get("host_ui"):
        payload = _inject_html_prefix(payload, ctype, prefix)
    loc = out_headers.get("Location") or out_headers.get("location")
    if loc and loc.startswith(upstream):
        out_headers["Location"] = prefix + loc[len(upstream) :]
    out_headers["Content-Type"] = ctype
    apply_cors(out_headers, req_headers)
    return status, out_headers, payload
