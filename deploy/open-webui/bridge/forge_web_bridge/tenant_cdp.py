"""Resolve per-tenant CDP URLs from the Lenses user gateway."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _settings() -> tuple[str, str]:
    base = os.getenv("FORGE_WEB_BRIDGE_TENANT_GATEWAY_URL", "http://127.0.0.1:8090").strip().rstrip("/")
    secret = os.getenv("FORGE_WEB_BRIDGE_TENANT_GATEWAY_SECRET", "").strip()
    return base, secret


def _provider_for_model(model: str, default_provider: str) -> str:
    model = (model or "").strip().lower()
    if model in ("tenant-chatgpt", "tenant-chatgpt-primary") or model.startswith("tenant-chatgpt"):
        return "chatgpt"
    if model in ("tenant-gemini", "tenant-gemini-primary") or model.startswith("tenant-gemini"):
        return "gemini"
    return default_provider


def tenant_uses_selector(model: str) -> bool:
    return (model or "").strip().lower().startswith("tenant-")


def resolve_tenant_cdp(user_email: str, provider: str) -> dict[str, Any]:
    email = (user_email or "").strip().lower()
    if "@" not in email:
        return {"ok": False, "connected": False, "detail": "missing_user_email"}
    base, secret = _settings()
    qs = urllib.parse.urlencode({"email": email, "provider": provider})
    req = urllib.request.Request(f"{base}/gateway/tenant-profile?{qs}")
    if secret:
        req.add_header("Authorization", f"Bearer {secret}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")[:500]
        except OSError:
            body = ""
        return {"ok": False, "connected": False, "detail": f"gateway_http_{exc.code}: {body}"}
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "connected": False, "detail": str(exc)}
    if not isinstance(data, dict):
        return {"ok": False, "connected": False, "detail": "invalid_gateway_response"}
    return data


def resolve_cdp_for_request(
    *,
    user_email: str | None,
    model: str,
    default_provider: str,
    default_cdp: str,
) -> tuple[str, str | None]:
    """Return (cdp_url, error_detail). error_detail set when tenant path required but unavailable."""
    if not tenant_uses_selector(model):
        return default_cdp, None
    if not (user_email or "").strip():
        return "", "Connect your Google account in Open WebUI so your email is forwarded to the bridge."
    provider = _provider_for_model(model, default_provider)
    hit = resolve_tenant_cdp(user_email or "", provider)
    if not hit.get("connected"):
        detail = str(hit.get("detail") or "").strip()
        if not detail:
            detail = f"Connect {provider.title()} in Lenses at /setup before using this model."
        return "", detail
    cdp = str(hit.get("cdp_url") or "").strip()
    if not cdp:
        return "", "Tenant browser session is not ready. Open Lenses /setup and connect again."
    return cdp, None