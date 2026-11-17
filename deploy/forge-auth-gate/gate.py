#!/usr/bin/env python3
"""Reverse proxy gate: Google sign-in via login.forgedc.net; Bearer/Basic pass-through."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

COOKIE_NAME = os.environ.get("FORGE_AUTH_GATE_COOKIE", "forge_gate")
GATE_SECRET = (os.environ.get("FORGE_AUTH_GATE_SECRET") or "").strip() or secrets.token_hex(32)
PUBLIC_ORIGIN = os.environ.get("FORGE_AUTH_GATE_PUBLIC_ORIGIN", "").rstrip("/")
UPSTREAM = os.environ.get("FORGE_AUTH_GATE_UPSTREAM", "http://127.0.0.1:8080").rstrip("/")
AUTH_ORIGIN = os.environ.get("FORGE_AUTH_GATE_LOGIN_ORIGIN", "https://login.forgedc.net").rstrip("/")
REDEEM_URL = os.environ.get(
    "FORGE_AUTH_GATE_REDEEM_URL",
    f"{AUTH_ORIGIN}/gateway/auth/redeem",
).strip()
MODE = (os.environ.get("FORGE_AUTH_GATE_MODE") or "webui").strip().lower()
TRUSTED_EMAIL_HEADER = (
    os.environ.get("FORGE_AUTH_GATE_TRUSTED_EMAIL_HEADER") or "X-Forwarded-Email"
).strip()
TRUSTED_NAME_HEADER = (os.environ.get("FORGE_AUTH_GATE_TRUSTED_NAME_HEADER") or "").strip()
MLFLOW_HMAC_SECRET = (os.environ.get("FORGE_AUTH_GATE_MLFLOW_HMAC_SECRET") or GATE_SECRET).encode("utf-8")
SESSION_TTL = int(os.environ.get("FORGE_AUTH_GATE_SESSION_TTL", "43200"))
LISTEN_HOST = os.environ.get("FORGE_AUTH_GATE_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("FORGE_AUTH_GATE_PORT", "19809"))

_STRIP_HEADERS = {
    TRUSTED_EMAIL_HEADER.lower(),
    "x-forwarded-email",
    "x-webui-email",
    "x-forwarded-user",
    "x-forwarded-preferred-username",
}
if TRUSTED_NAME_HEADER:
    _STRIP_HEADERS.add(TRUSTED_NAME_HEADER.lower())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_cookie(email: str, name: str, exp: float) -> str:
    payload = {"email": email, "name": name, "exp": exp}
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(GATE_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _read_cookie(raw: str) -> dict[str, str] | None:
    if not raw or "." not in raw:
        return None
    body, sig = raw.rsplit(".", 1)
    expect = hmac.new(GATE_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None
    exp = float(payload.get("exp") or 0)
    if exp < time.time():
        return None
    email = str(payload.get("email") or "").strip().lower()
    if "@" not in email:
        return None
    return {"email": email, "name": str(payload.get("name") or email)}


def _mlflow_password(email: str) -> str:
    digest = hmac.new(MLFLOW_HMAC_SECRET, email.lower().encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:24]


def _parse_upstream(url: str) -> tuple[str, int, bool, str]:
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or ""
    return host, port, scheme == "https", path


def _redeem_ticket(ticket: str) -> dict[str, Any] | None:
    data = json.dumps({"ticket": ticket}).encode("utf-8")
    req = urllib.request.Request(
        REDEEM_URL,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body if body.get("ok") is True else None
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


class GateHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[forge-auth-gate] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def _dispatch(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/_forge_auth/health":
            payload = json.dumps({"ok": True, "service": "forge-auth-gate", "mode": MODE}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return
        if parsed.path == "/_forge_auth/finish":
            ticket = (urllib.parse.parse_qs(parsed.query).get("ticket") or [""])[0]
            if not ticket:
                self.send_error(400, "missing ticket")
                return
            profile = _redeem_ticket(ticket)
            if not profile:
                self.send_error(401, "ticket invalid")
                return
            email = str(profile.get("email") or "").lower()
            name = str(profile.get("display_name") or email)
            exp = time.time() + SESSION_TTL
            cookie_val = _sign_cookie(email, name, exp)
            loc = PUBLIC_ORIGIN + "/" if PUBLIC_ORIGIN else "/"
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header(
                "Set-Cookie",
                f"{COOKIE_NAME}={cookie_val}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}",
            )
            self.end_headers()
            return
        authz = (self.headers.get("Authorization") or "").strip()
        if authz:
            self._proxy(extra_headers={})
            return
        session = _read_cookie(self._cookie_value())
        if not session:
            if PUBLIC_ORIGIN:
                rt = urllib.parse.quote(PUBLIC_ORIGIN, safe="")
                loc = f"{AUTH_ORIGIN}/api/auth/oidc/start?return_to={rt}"
            else:
                loc = f"{AUTH_ORIGIN}/api/auth/oidc/start"
            self.send_response(302)
            self.send_header("Location", loc)
            self.end_headers()
            return
        extra: dict[str, str] = {}
        if MODE == "webui":
            extra[TRUSTED_EMAIL_HEADER] = session["email"]
            if TRUSTED_NAME_HEADER:
                extra[TRUSTED_NAME_HEADER] = session.get("name") or session["email"]
        elif MODE == "mlflow":
            user = session["email"]
            pwd = _mlflow_password(user)
            token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            extra["Authorization"] = f"Basic {token}"
        self._proxy(extra_headers=extra)

    def _cookie_value(self) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            chunk = part.strip()
            if chunk.startswith(f"{COOKIE_NAME}="):
                return chunk.split("=", 1)[1]
        return ""

    def _proxy(self, extra_headers: dict[str, str]) -> None:
        host, port, use_tls, _base = _parse_upstream(UPSTREAM)
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length and self.command not in ("GET", "HEAD") else None
        headers: dict[str, str] = {}
        for key, val in self.headers.items():
            lk = key.lower()
            if lk in ("host", "connection", "content-length", "transfer-encoding"):
                continue
            if lk in _STRIP_HEADERS:
                continue
            headers[key] = val
        for key, val in extra_headers.items():
            headers[key] = val
        headers["Host"] = f"{host}:{port}" if port not in (80, 443) else host
        conn: HTTPConnection | HTTPSConnection
        if use_tls:
            conn = HTTPSConnection(host, port, timeout=120, context=ssl.create_default_context())
        else:
            conn = HTTPConnection(host, port, timeout=120)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            for hk, hv in resp.getheaders():
                lk = hk.lower()
                if lk in ("transfer-encoding", "connection"):
                    continue
                self.send_header(hk, hv)
            data = resp.read()
            if not resp.getheader("Content-Length") and data:
                self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except (TimeoutError, OSError, socket.error) as exc:
            self.send_error(502, str(exc))
        finally:
            conn.close()


def main() -> None:
    if not PUBLIC_ORIGIN:
        raise SystemExit("FORGE_AUTH_GATE_PUBLIC_ORIGIN is required")
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), GateHandler)
    print(f"[forge-auth-gate] {LISTEN_HOST}:{LISTEN_PORT} mode={MODE} public={PUBLIC_ORIGIN} upstream={UPSTREAM}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()