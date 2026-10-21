"""HTTP request guard: rate limits, blocks, sessions, scoped tokens."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from fleet_server import fleet_sessions, inbound_tokens, route_registry, security_store
from fleet_server.fleet_sessions import AuthContext

GuardMode = Literal["observe", "enforce"]

# Per client address, per 60s. `read` is Fleet's own JSON. `proxy` is a product UI
# (Market Studio and others) served under `/v1/app-gateways/<id>/…`, which polls
# several times a second and must not share the Fleet JSON budget.
LIMITS = {"read": 300, "mutate": 120, "heavy": 6, "public": 60, "proxy": 1200}
BODY_LIMIT = {
    "read": 1_048_576,
    "mutate": 1_048_576,
    "heavy": 2_097_152,
    "public": 65536,
    "proxy": 64 * 1024 * 1024,
}


@dataclass
class GuardDecision:
    allow: bool
    http_code: int = 200
    body: dict[str, Any] | None = None
    auth: AuthContext | None = None
    observe_only: bool = False
    delay_s: float = 0.0


class GuardState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.buckets: dict[str, list[float]] = {}
        self.auth_failures: dict[str, list[float]] = {}
        self.fail_counts_global: list[float] = []
        self.distinct_401_sources: dict[str, float] = {}
        self.scan_paths: dict[str, dict[str, float]] = {}
        self.siege_until: float = 0.0
        self.session_nonce: dict[str, float] = {}
        self.session_rate: dict[str, list[float]] = {}
        self.heavy_inflight = 0
        self.quarantined_tokens: set[str] = set()
        self.canary_hashes: set[str] = set()
        self.rotated_hashes: set[str] = set()
        self.mint_sources: dict[str, list[tuple[str, float]]] = {}
        self.agent_muted_until: float = 0.0
        self.pending_confirm: dict[str, dict[str, Any]] = {}


_STATE = GuardState()


def guard_mode() -> GuardMode:
    raw = str(os.environ.get("FLEET_GUARD_MODE", "enforce") or "enforce").strip().lower()
    return "observe" if raw == "observe" else "enforce"


def bearer_direct_mode() -> str:
    return str(os.environ.get("FLEET_BEARER_DIRECT", "") or "").strip().lower()


def trusted_proxy_peer(client: str) -> bool:
    cidrs = str(os.environ.get("FLEET_TRUSTED_PROXY_CIDRS", "127.0.0.0/8,::1/128") or "").split(",")
    try:
        addr = ipaddress.ip_address(client)
    except ValueError:
        return False
    for c in cidrs:
        c = c.strip()
        if not c:
            continue
        try:
            if addr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_source(headers: Any, peer: str) -> str:
    xff = str(headers.get("X-Forwarded-For") or "").strip()
    if xff and trusted_proxy_peer(peer):
        return xff.split(",")[0].strip()
    return peer.split(":")[0] if peer else "unknown"


def _bucket_key(source: str, route_class: str) -> str:
    return f"{source}:{route_class}"


def _take_bucket(state: GuardState, source: str, route_class: str, now: float, limit: int) -> bool:
    key = _bucket_key(source, route_class)
    window = 60.0
    with state._lock:
        hits = [t for t in state.buckets.get(key, []) if now - t < window]
        if len(hits) >= limit:
            state.buckets[key] = hits
            return False
        hits.append(now)
        state.buckets[key] = hits
    return True


def _record_auth_failure(state: GuardState, source: str, now: float) -> None:
    with state._lock:
        fails = [t for t in state.auth_failures.get(source, []) if now - t < 600]
        fails.append(now)
        state.auth_failures[source] = fails
        state.fail_counts_global = [t for t in state.fail_counts_global if now - t < 60]
        state.fail_counts_global.append(now)
        state.distinct_401_sources[source] = now
        if len(fails) >= 5:
            ttl = min(60.0, 60.0 * (2 ** min(len(fails) - 5, 4)))
            return ttl
    return 0.0


def _check_siege(state: GuardState, now: float) -> bool:
    with state._lock:
        if state.siege_until > now:
            return True
        global_fails = len([t for t in state.fail_counts_global if now - t < 60])
        recent_sources = len(
            [s for s, t in state.distinct_401_sources.items() if now - t < 300]
        )
        if global_fails > 30 or recent_sources > 25:
            state.siege_until = now + 900
            return True
    return False


def _scope_allows(required: route_registry.Scope, scopes: frozenset[str]) -> bool:
    if "admin" in scopes:
        return True
    if required == "public":
        return True
    if required == "admin":
        return "admin" in scopes
    return required in scopes


def _extract_bearer(headers: Any) -> str:
    auth = str(headers.get("Authorization") or "")
    m = re.match(r"Bearer\s+(.+)", auth, re.I)
    return (m.group(1) if m else "").strip()


def load_canary_and_rotated(data_dir: Any) -> None:
    from pathlib import Path

    d = Path(data_dir)
    for name in ("forge-fleet.env.bak", "remote-peers.json.bak"):
        p = d / "etc" / name
        if not p.is_file():
            p = d.parent / name if False else p
        env_bak = Path(os.path.expanduser("~/.config/forge-fleet/forge-fleet.env.bak"))
        if env_bak.is_file():
            for line in env_bak.read_text(encoding="utf-8").splitlines():
                if line.startswith("FLEET_BEARER_TOKEN="):
                    val = line.split("=", 1)[1].strip().strip('"')
                    if val:
                        _STATE.canary_hashes.add(inbound_tokens.hash_token(val))
    rot = d / "etc" / "rotated-token-hashes.json"
    if rot.is_file():
        try:
            doc = json.loads(rot.read_text(encoding="utf-8"))
            for h in doc.get("hashes") or []:
                _STATE.rotated_hashes.add(str(h))
        except (OSError, json.JSONDecodeError):
            pass


def evaluate(
    *,
    db_path: Any,
    data_dir: Any,
    method: str,
    path: str,
    headers: Any,
    peer: str,
    body: bytes,
    expected_token: str,
    loopback_skips_auth: bool,
    listen_host: str,
) -> GuardDecision:
    from pathlib import Path
    import sqlite3

    from fleet_server import store

    now = time.time()
    source = client_source(headers, peer)
    route_class = route_registry.route_class_for_path(path, method)
    required_scope = route_registry.scope_for_path(path, method)
    request_id = uuid.uuid4().hex[:16]
    mode = guard_mode()
    state = _STATE

    conn = store.connect(Path(db_path))
    try:
        blocked, rule = security_store.is_blocked(conn, source, now)
        if blocked:
            security_store.insert_event(
                conn,
                source=source,
                verdict="deny",
                severity="medium",
                path=path,
                method=method,
                rule=rule or "blocked",
                request_id=request_id,
            )
            dec = GuardDecision(allow=False, http_code=429, body={"ok": False, "error": "blocked"})
            return _observe(dec, mode)

        if _check_siege(state, now) and path != "/v1/health":
            if not headers.get("X-Fleet-Session"):
                dec = GuardDecision(
                    allow=False,
                    http_code=401,
                    body={"ok": False, "error": "unauthorized"},
                    delay_s=1.0,
                )
                return _observe(dec, mode)

        if len(body) > BODY_LIMIT.get(route_class, BODY_LIMIT["read"]):
            dec = GuardDecision(allow=False, http_code=413, body={"ok": False, "error": "body_too_large"})
            return _observe(dec, mode)

        # Session fast path
        sid = str(headers.get("X-Fleet-Session") or "").strip()
        sig = str(headers.get("X-Fleet-Sig") or "").strip()
        if sid and sig:
            auth = fleet_sessions.verify_session_request(
                conn,
                session_id=sid,
                signature=sig,
                method=method,
                path=path,
                body=body,
                source=source,
                user_agent=str(headers.get("User-Agent") or "")[:500],
                nonce_cache=state.session_nonce,
                now=now,
            )
            if auth.ok:
                    hits = state.session_rate.get(sid, [])
                    hits = [t for t in hits if now - t < 60]
                    if len(hits) < 600:
                        hits.append(now)
                        state.session_rate[sid] = hits
                        if not _scope_allows(required_scope, auth.scopes):
                            dec = GuardDecision(
                                allow=False,
                                http_code=403,
                                body={"ok": False, "error": "forbidden"},
                                auth=auth,
                            )
                            return _observe(dec, mode)
                        if route_class == "heavy":
                            if state.heavy_inflight >= 1:
                                dec = GuardDecision(
                                    allow=False,
                                    http_code=429,
                                    body={"ok": False, "error": "heavy_busy"},
                                )
                                return _observe(dec, mode)
                            state.heavy_inflight += 1
                        return GuardDecision(allow=True, auth=auth)
            dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
            return _observe(dec, mode)

        # Public health — rate limit only
        if path == "/v1/health" and method == "GET":
            if not _take_bucket(state, source, "public", now, LIMITS["public"]):
                dec = GuardDecision(allow=False, http_code=429, body={"ok": False, "error": "rate_limited"})
                return _observe(dec, mode)
            bearer = _extract_bearer(headers)
            if bearer and expected_token and hmac.compare_digest(bearer, expected_token.strip()):
                auth = AuthContext(ok=True, scopes=frozenset({"admin"}), is_admin=True, source=source)
                return GuardDecision(allow=True, auth=auth, body={"health_mode": "full"})
            if loopback_skips_auth and _is_loopback_peer(peer):
                auth = AuthContext(ok=True, scopes=frozenset({"admin"}), is_admin=True, source=source)
                return GuardDecision(allow=True, auth=auth, body={"health_mode": "full"})
            return GuardDecision(allow=True, body={"health_mode": "minimal"})

        if not path.startswith("/v1/"):
            return GuardDecision(allow=True)

        if not _take_bucket(state, source, route_class, now, LIMITS.get(route_class, LIMITS["read"])):
            security_store.insert_event(
                conn,
                source=source,
                verdict="deny",
                severity="medium",
                rule="rate_limit",
                path=path,
                method=method,
                request_id=request_id,
            )
            dec = GuardDecision(allow=False, http_code=429, body={"ok": False, "error": "rate_limited"})
            return _observe(dec, mode)

        bearer = _extract_bearer(headers)
        if bearer:
            digest = inbound_tokens.hash_token(bearer)
            if digest in state.canary_hashes:
                security_store.upsert_block(conn, source, now + 86400, "canary", "honeytoken")
                security_store.insert_event(
                    conn,
                    source=source,
                    verdict="deny",
                    severity="critical",
                    rule="canary",
                    path=path,
                    method=method,
                    request_id=request_id,
                )
                dec = GuardDecision(allow=False, http_code=403, body={"ok": False, "error": "forbidden"})
                return _observe(dec, mode)
            if digest in state.rotated_hashes:
                security_store.insert_event(
                    conn,
                    source=source,
                    verdict="deny",
                    severity="high",
                    rule="rotated_token",
                    path=path,
                    method=method,
                    request_id=request_id,
                )
                dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
                return _observe(dec, mode)

        if loopback_skips_auth and _is_loopback_peer(peer) and not bearer:
            auth = AuthContext(ok=True, scopes=frozenset({"admin"}), is_admin=True, source=source)
            return GuardDecision(allow=True, auth=auth)

        if not bearer and path == "/v1/auth/session" and method == "POST":
            dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
            return _observe(dec, mode)

        direct_mode = bearer_direct_mode()
        if bearer and direct_mode == "mint-only" and path != "/v1/auth/session":
            if not (_is_loopback_peer(peer) and loopback_skips_auth):
                dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
                return _observe(dec, mode)

        token_id: str | None = None
        scopes: frozenset[str] = frozenset()
        err: str | None = None
        if bearer:
            token_id, scopes, err = inbound_tokens.resolve_token(
                Path(data_dir), bearer, expected_token, source=source, now=now
            )
            if token_id and token_id in state.quarantined_tokens:
                err = "quarantined"
            if err:
                ttl = _record_auth_failure(state, source, now)
                if ttl:
                    security_store.upsert_block(conn, source, now + ttl, "auth_failures", err)
                security_store.insert_event(
                    conn,
                    source=source,
                    verdict="deny",
                    severity="high" if err == "out_of_binding" else "low",
                    rule=err,
                    path=path,
                    method=method,
                    request_id=request_id,
                )
                dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
                return _observe(dec, mode)
            if not token_id:
                ttl = _record_auth_failure(state, source, now)
                if ttl:
                    security_store.upsert_block(conn, source, now + ttl, "auth_failures", "invalid")
                dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
                return _observe(dec, mode)
            auth = AuthContext(
                ok=True,
                scopes=scopes,
                token_id=token_id,
                source=source,
                is_admin="admin" in scopes,
            )
            if not _scope_allows(required_scope, scopes):
                security_store.insert_event(
                    conn,
                    source=source,
                    verdict="deny",
                    severity="high",
                    rule="scope_climb",
                    path=path,
                    method=method,
                    token_scope=",".join(sorted(scopes)),
                    request_id=request_id,
                )
                state.quarantined_tokens.add(token_id)
                dec = GuardDecision(allow=False, http_code=403, body={"ok": False, "error": "forbidden"}, auth=auth)
                return _observe(dec, mode)
            if path == "/v1/auth/session" and method == "POST":
                with state._lock:
                    state.mint_sources.setdefault(token_id or "admin", []).append((source, now))
            return GuardDecision(allow=True, auth=auth)

        if route_registry.match_route(path, method) is None:
            if _record_scan_path(state, source, path, now):
                security_store.upsert_block(conn, source, now + 900, "scan", "404_scan")
                security_store.insert_event(
                    conn,
                    source=source,
                    verdict="deny",
                    severity="medium",
                    rule="scan",
                    path=path,
                    method=method,
                    request_id=request_id,
                )
            dec = GuardDecision(allow=False, http_code=404, body={"ok": False, "error": "not_found"})
            return _observe(dec, mode)

        dec = GuardDecision(allow=False, http_code=401, body={"ok": False, "error": "unauthorized"})
        return _observe(dec, mode)
    finally:
        conn.close()


def release_heavy() -> None:
    with _STATE._lock:
        _STATE.heavy_inflight = max(0, _STATE.heavy_inflight - 1)


def _record_scan_path(state: GuardState, source: str, path: str, now: float) -> bool:
    """Return True when distinct 404 paths in 5m exceeds threshold (auto-block)."""
    with state._lock:
        bucket = state.scan_paths.setdefault(source, {})
        bucket[path] = now
        recent = {p: t for p, t in bucket.items() if now - t < 300}
        state.scan_paths[source] = recent
        return len(recent) > 20


def _is_loopback_peer(peer: str) -> bool:
    host = peer.rsplit(":", 1)[0] if peer else ""
    return host in ("127.0.0.1", "::1", "localhost")


def _observe(dec: GuardDecision, mode: GuardMode) -> GuardDecision:
    if mode == "observe" and not dec.allow:
        dec.observe_only = True
        dec.allow = True
    return dec


def events_payload(db_path: Any, period_sec: float) -> dict[str, Any]:
    from pathlib import Path

    from fleet_server import store

    since = time.time() - period_sec
    conn = store.connect(Path(db_path))
    try:
        rows = security_store.list_events(conn, since)
    finally:
        conn.close()
    return {"ok": True, "events": rows, "period_sec": period_sec}


def blocks_payload(db_path: Any) -> dict[str, Any]:
    from pathlib import Path

    from fleet_server import store

    conn = store.connect(Path(db_path))
    try:
        rows = security_store.list_blocks(conn)
    finally:
        conn.close()
    return {"ok": True, "blocks": rows, "siege_active": _STATE.siege_until > time.time()}
