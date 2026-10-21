"""Signed Fleet API sessions (mint, verify, persist)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fleet_server import security_store

SESSION_SLIDING_SEC = 3600
SESSION_ABSOLUTE_SEC = 12 * 3600
SIGNATURE_WINDOW_SEC = 120
NONCE_TTL_SEC = 120


@dataclass
class AuthContext:
    ok: bool
    scopes: frozenset[str]
    session_id: str | None = None
    token_id: str | None = None
    source: str = ""
    is_admin: bool = False
    error: str | None = None


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def mint_session(
    conn: sqlite3.Connection,
    *,
    scopes: list[str],
    source: str,
    user_agent: str,
    token_id: str | None = None,
) -> dict[str, Any]:
    session_id = uuid.uuid4().hex
    secret = secrets.token_urlsafe(32)
    now = time.time()
    expires = now + SESSION_SLIDING_SEC
    absolute = now + SESSION_ABSOLUTE_SEC
    conn.execute(
        """
        INSERT INTO fleet_auth_sessions
            (session_id, secret_hash, session_secret, scopes_json, source, user_agent, minted_at, expires_at, absolute_expires_at, last_used_at, token_id, revoked)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            session_id,
            _hash_secret(secret),
            secret,
            json.dumps(scopes),
            source,
            user_agent[:500],
            now,
            expires,
            absolute,
            now,
            token_id,
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "session_id": session_id,
        "session_secret": secret,
        "expires_at": expires,
        "scopes": scopes,
    }


def revoke_session(conn: sqlite3.Connection, session_id: str) -> bool:
    cur = conn.execute(
        "UPDATE fleet_auth_sessions SET revoked = 1 WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    return int(cur.rowcount or 0) > 0


def list_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT session_id, scopes_json, source, user_agent, minted_at, expires_at, absolute_expires_at, last_used_at, token_id, revoked
        FROM fleet_auth_sessions WHERE revoked = 0 AND expires_at > ?
        """,
        (time.time(),),
    ).fetchall()
    out = []
    for r in rows:
        try:
            scopes = json.loads(str(r["scopes_json"] or "[]"))
        except json.JSONDecodeError:
            scopes = []
        out.append(
            {
                "session_id": r["session_id"],
                "scopes": scopes,
                "source": r["source"],
                "user_agent": r["user_agent"],
                "minted_at": float(r["minted_at"]),
                "expires_at": float(r["expires_at"]),
                "last_used_at": float(r["last_used_at"]),
                "token_id": r["token_id"],
            }
        )
    return out


def _body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _signature_payload(method: str, path: str, minute: int, body_hash: str) -> bytes:
    return f"{method.upper()}|{path}|{minute}|{body_hash}".encode("utf-8")


def verify_session_request(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    signature: str,
    method: str,
    path: str,
    body: bytes,
    source: str,
    user_agent: str,
    nonce_cache: dict[str, float],
    now: float | None = None,
) -> AuthContext:
    now = now if now is not None else time.time()
    row = conn.execute(
        """
        SELECT secret_hash, session_secret, scopes_json, source, user_agent, expires_at, absolute_expires_at, revoked, token_id
        FROM fleet_auth_sessions WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None or int(row["revoked"] or 0):
        return AuthContext(ok=False, scopes=frozenset(), error="session_invalid")
    if now > float(row["absolute_expires_at"]) or now > float(row["expires_at"]):
        return AuthContext(ok=False, scopes=frozenset(), error="session_expired")
    session_secret = str(row["session_secret"] or "")
    if not session_secret or not hmac.compare_digest(_hash_secret(session_secret), str(row["secret_hash"])):
        return AuthContext(ok=False, scopes=frozenset(), error="session_invalid")
    if not verify_session_signature(session_secret, method, path, body, signature, now):
        return AuthContext(ok=False, scopes=frozenset(), error="session_invalid")
    bound_source = str(row["source"] or "")
    if bound_source and bound_source != source:
        security_store.insert_event(
            conn,
            source=source,
            verdict="deny",
            severity="high",
            rule="session_hijack_suspected",
            session_id=session_id,
            detail={"bound_source": bound_source},
        )
        revoke_session(conn, session_id)
        return AuthContext(ok=False, scopes=frozenset(), error="session_binding")
    body_hash = _body_sha256(body)
    minute = int(now // 60)
    nonce_key = f"{session_id}:{body_hash}:{minute}"
    if nonce_key in nonce_cache and (now - nonce_cache[nonce_key]) < NONCE_TTL_SEC:
        return AuthContext(ok=False, scopes=frozenset(), error="replay")
    try:
        scopes_list = json.loads(str(row["scopes_json"] or "[]"))
    except json.JSONDecodeError:
        scopes_list = []
    scopes = frozenset(str(s) for s in scopes_list)
    new_exp = min(float(row["absolute_expires_at"]), now + SESSION_SLIDING_SEC)
    conn.execute(
        "UPDATE fleet_auth_sessions SET last_used_at = ?, expires_at = ? WHERE session_id = ?",
        (now, new_exp, session_id),
    )
    conn.commit()
    nonce_cache[nonce_key] = now
    return AuthContext(
        ok=True,
        scopes=scopes,
        session_id=session_id,
        token_id=str(row["token_id"] or "") or None,
        source=source,
        is_admin="admin" in scopes,
    )


def verify_session_signature(
    session_secret: str,
    method: str,
    path: str,
    body: bytes,
    sig: str,
    now: float | None = None,
) -> bool:
    now = now if now is not None else time.time()
    body_hash = _body_sha256(body)
    minute = int(now // 60)
    for delta in (0, -1):
        payload = _signature_payload(method, path, minute + delta, body_hash)
        expected = hmac.new(session_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, (sig or "").strip().lower()):
            return True
    return False
