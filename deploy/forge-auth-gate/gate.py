#!/usr/bin/env python3
"""Reverse proxy gate: Google sign-in via login.forgedc.net; Bearer/Basic pass-through."""

from __future__ import annotations

import html
import base64
from pathlib import Path

from completion_jobs import JOB_COLLECTION, CompletionJobs, job_id_from_path
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
PROXY_TIMEOUT = int(os.environ.get("FORGE_AUTH_GATE_PROXY_TIMEOUT", "360"))
_JOBS = CompletionJobs(
    Path(os.environ.get("FORGE_AUTH_GATE_JOB_DIR", "/tmp/forge-auth-gate-jobs")),
    UPSTREAM,
)

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


_ensured_users: set[str] = set()
_ensure_lock = threading.Lock()


def _mlflow_admin_basic() -> str | None:
    user = (os.environ.get("FORGE_AUTH_GATE_MLFLOW_ADMIN_USERNAME") or "").strip()
    password = (os.environ.get("FORGE_AUTH_GATE_MLFLOW_ADMIN_PASSWORD") or "").strip()
    ini_path = (os.environ.get("FORGE_AUTH_GATE_MLFLOW_AUTH_INI") or "").strip()
    if ini_path and (not user or not password):
        try:
            for line in open(ini_path, encoding="utf-8"):
                chunk = line.strip()
                if chunk.startswith("admin_username") and "=" in chunk:
                    user = user or chunk.split("=", 1)[1].strip()
                elif chunk.startswith("admin_password") and "=" in chunk:
                    password = password or chunk.split("=", 1)[1].strip()
        except OSError:
            return None
    if not user or not password:
        return None
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _mlflow_admin_request(method: str, path: str, body: bytes, admin: str) -> int:
    url = f"{UPSTREAM}{path}"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Authorization": admin, "Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code


def _inject_sign_out(data: bytes) -> bytes:
    bar = (
        b'<div style="position:fixed;top:8px;right:12px;z-index:2147483647">'
        b'<a href="/_forge_auth/logout" style="font:13px sans-serif;background:#1c1915;'
        b'color:#f4f1ea;padding:6px 10px;text-decoration:none">Sign out</a></div>'
    )
    lower = data.lower()
    idx = lower.rfind(b"</body>")
    if idx == -1:
        return bar + data
    return data[:idx] + bar + data[idx:]


def _ensure_mlflow_user(email: str) -> bool:
    """Create or align the MLflow basic-auth user for a Google email."""
    with _ensure_lock:
        if email in _ensured_users:
            return True
    admin = _mlflow_admin_basic()
    if admin is None:
        return False
    body = json.dumps({"username": email, "password": _mlflow_password(email)}).encode("utf-8")
    created = _mlflow_admin_request("POST", "/api/2.0/mlflow/users/create", body, admin)
    if created not in (200, 201):
        updated = _mlflow_admin_request("PATCH", "/api/2.0/mlflow/users/update-password", body, admin)
        if updated not in (200, 201):
            return False
    with _ensure_lock:
        _ensured_users.add(email)
    return True


def _parse_upstream(url: str) -> tuple[str, int, bool, str]:
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or ""
    return host, port, scheme == "https", path


def session_upstream_headers(session: dict[str, str]) -> dict[str, str] | None:
    """Headers added for a Google session. MLflow mode signs the user in with basic auth instead."""
    if MODE == "mlflow":
        return None
    email = str(session.get("email") or "").strip()
    if not email:
        return {}
    extra = {TRUSTED_EMAIL_HEADER: email}
    if TRUSTED_NAME_HEADER:
        extra[TRUSTED_NAME_HEADER] = str(session.get("name") or email)
    return extra


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
        if parsed.path == JOB_COLLECTION or parsed.path.startswith(JOB_COLLECTION + "/"):
            self._completion_job(parsed.path)
            return
        if parsed.path == "/_forge_auth/health":
            payload = json.dumps({"ok": True, "service": "forge-auth-gate", "mode": MODE}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            return
        if parsed.path == "/_forge_auth/logout":
            self._signed_out_page()
            return
        if parsed.path == "/_forge_auth/login":
            self._redirect(self._google_start())
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
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
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
            if self._browser_document():
                self._sign_in_page()
            else:
                self.send_error(401, "Sign in required")
            return
        extra: dict[str, str] = {}
        if MODE == "mlflow":
            user = session["email"]
            if not _ensure_mlflow_user(user):
                self.send_error(502, "MLflow user was not created for this Google account")
                return
            pwd = _mlflow_password(user)
            token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            extra["Authorization"] = f"Basic {token}"
        else:
            extra = session_upstream_headers(session) or {}
        self._proxy(extra_headers=extra)

    def _completion_job(self, path: str) -> None:
        authz = (self.headers.get("Authorization") or "").strip()
        if not authz.lower().startswith("bearer "):
            self._json(401, {"error": "bearer required"})
            return
        if path.rstrip("/") == JOB_COLLECTION:
            if self.command != "POST":
                self._json(405, {"error": "POST"})
                return
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0 or length > 2_000_000:
                self._json(400, {"error": "completion body is required"})
                return
            body = self.rfile.read(length)
            record = _JOBS.start(authz, body)
            self._json(202, record, retry_after=int(record.get("retry_after") or 20))
            return
        job_id = job_id_from_path(path)
        if self.command != "GET" or not job_id:
            self._json(404, {"error": "job not found"})
            return
        record = _JOBS.read(job_id)
        if record is None:
            self._json(404, {"error": "job not found"})
            return
        status = str(record.get("status") or "")
        code = 202 if status == "running" else 200
        retry_after = int(record.get("retry_after") or 0) if status in {"running", "limited"} else None
        self._json(code, record, retry_after=retry_after)

    def _json(self, status: int, payload: dict, *, retry_after: int | None = None) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if retry_after:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _google_start(self) -> str:
        if not PUBLIC_ORIGIN:
            return f"{AUTH_ORIGIN}/api/auth/oidc/start"
        rt = urllib.parse.quote(PUBLIC_ORIGIN, safe="")
        return f"{AUTH_ORIGIN}/api/auth/oidc/start?return_to={rt}"

    def _browser_document(self) -> bool:
        if self.command != "GET":
            return False
        path = urllib.parse.urlparse(self.path).path or "/"
        if path.startswith(("/api/", "/ajax-api/", "/static/", "/assets/", "/_forge_auth/")):
            return False
        accept = (self.headers.get("Accept") or "").lower()
        return "text/html" in accept or path == "/"

    def _html(self, status: int, title: str, body: str, extra: list[tuple[str, str]] | None = None) -> None:
        page = (
            "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{title}</title></head><body style=\"font-family:Georgia,serif;"
            "background:#f4f1ea;color:#1c1915;max-width:36rem;margin:4rem auto;padding:0 1rem\">"
            f"<h1>{title}</h1>{body}</body></html>"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        for key, val in extra or []:
            self.send_header(key, val)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(page)

    def _sign_in_page(self) -> None:
        start = html.escape(self._google_start())
        self._html(
            200,
            "Sign in",
            f"<p>This service uses the Forge Google account.</p>"
            f"<p><a href=\"{start}\">Sign in with Google</a></p>",
        )

    def _signed_out_page(self) -> None:
        start = html.escape(self._google_start())
        self._html(
            200,
            "Signed out",
            f"<p>You are signed out of this host. The Google account in the browser is unchanged.</p>"
            f"<p><a href=\"{start}\">Sign in with Google</a></p>",
            [("Set-Cookie", f"{COOKIE_NAME}=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0")],
        )

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
            conn = HTTPSConnection(host, port, timeout=PROXY_TIMEOUT, context=ssl.create_default_context())
        else:
            conn = HTTPConnection(host, port, timeout=PROXY_TIMEOUT)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status)
            data = resp.read()
            ctype = (resp.getheader("Content-Type") or "").lower()
            rewrite = (
                bool(extra_headers)
                and self.command != "HEAD"
                and "text/html" in ctype
                and not resp.getheader("Content-Encoding")
            )
            if rewrite:
                data = _inject_sign_out(data)
            for hk, hv in resp.getheaders():
                lk = hk.lower()
                if lk in ("transfer-encoding", "connection", "content-length"):
                    continue
                self.send_header(hk, hv)
            if data and self.command != "HEAD":
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