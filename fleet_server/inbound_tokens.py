"""Scoped inbound API tokens (hashed on disk)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from typing import Any


def _path(data_dir: Path) -> Path:
    return data_dir / "etc" / "inbound-tokens.json"


def load_tokens(data_dir: Path) -> list[dict[str, Any]]:
    p = _path(data_dir)
    if not p.is_file():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = doc.get("tokens") if isinstance(doc, dict) else doc
    return [r for r in rows or [] if isinstance(r, dict)]


def save_tokens(data_dir: Path, tokens: list[dict[str, Any]]) -> None:
    p = _path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"tokens": tokens}, indent=2) + "\n", encoding="utf-8")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def issue_token(
    data_dir: Path,
    *,
    label: str,
    scopes: list[str],
    allowed_sources: list[str] | None = None,
    allowed_hours: str | None = None,
    ttl_days: int | None = None,
) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    token_id = secrets.token_hex(8)
    expires = None
    if ttl_days:
        expires = time.time() + ttl_days * 86400
    entry = {
        "id": token_id,
        "label": label,
        "token_hash": hash_token(raw),
        "scopes": scopes,
        "allowed_sources": allowed_sources or [],
        "allowed_hours": allowed_hours,
        "expires": expires,
        "created_at": time.time(),
    }
    tokens = load_tokens(data_dir)
    tokens.append(entry)
    save_tokens(data_dir, tokens)
    return token_id, raw


def resolve_token(
    data_dir: Path,
    presented: str,
    admin_token: str,
    *,
    source: str,
    now: float | None = None,
) -> tuple[str | None, frozenset[str], str | None]:
    """Return (token_id, scopes, error). admin_token matches → admin scope."""
    now = now if now is not None else time.time()
    if admin_token and hmac.compare_digest(presented.strip(), admin_token.strip()):
        return "admin-bearer", frozenset({"admin"}), None
    digest = hash_token(presented)
    for row in load_tokens(data_dir):
        if not hmac.compare_digest(str(row.get("token_hash") or ""), digest):
            continue
        exp = row.get("expires")
        if exp is not None and float(exp) < now:
            return str(row.get("id") or ""), frozenset(), "expired"
        allowed = row.get("allowed_sources") or []
        if allowed and not _source_allowed(source, allowed):
            return str(row.get("id") or ""), frozenset(), "out_of_binding"
        hours = row.get("allowed_hours")
        if hours and not _hours_ok(hours, now):
            return str(row.get("id") or ""), frozenset(), "out_of_binding"
        scopes = frozenset(str(s) for s in (row.get("scopes") or []))
        return str(row.get("id") or ""), scopes, None
    return None, frozenset(), "invalid"


def _source_allowed(source: str, cidrs: list[str]) -> bool:
    if not cidrs:
        return True
    for c in cidrs:
        c = str(c).strip()
        if not c:
            continue
        if "/" in c:
            # minimal prefix: same first three octets for /24
            if c.endswith("/24"):
                base = c.split("/")[0].rsplit(".", 1)[0]
                if source.startswith(base + "."):
                    return True
        elif source == c:
            return True
    return False


def _hours_ok(spec: str, now: float) -> bool:
    # format "9-17" UTC hours inclusive
    try:
        a, b = spec.split("-", 1)
        lo, hi = int(a), int(b)
        hour = int(time.gmtime(now).tm_hour)
        return lo <= hour <= hi
    except (ValueError, AttributeError):
        return True
