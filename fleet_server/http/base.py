"""FleetHandler helpers and response utilities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fleet_server import (
    container_layout,
    container_templates,
    forge_llm_service,
    host_stats,
    runner,
    self_update,
    store,
    telemetry_periods,
    templates_catalog,
    thermal_llm_policy,
    versioning,
    workspace_bundle,
)
from fleet_server.test_fleet import spawn_test_fleet


def json_bytes(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


class FleetHandlerBase(BaseHTTPRequestHandler):
    server_version = versioning.fleet_server_version_string()
    db_path: Path
    expected_token: str

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    def _send_raw(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_admin_shell(self) -> None:
        try:
            from fleet_server.admin_shell import assemble_admin_html_bytes

            data = assemble_admin_html_bytes()
        except OSError:
            self._send_raw(500, b"admin bundle missing", "text/plain; charset=utf-8")
            return
        self._send_raw(200, data, "text/html; charset=utf-8")

    def _serve_admin_packaged_static(self, rel: str) -> None:
        """Static assets under ``fleet_server/static/`` (GPU logos, admin JS/CSS)."""
        rel = rel.replace("\\", "/").strip("/")
        if not rel or ".." in rel.split("/"):
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        parts = rel.split("/")
        static_parts: tuple[str, ...]
        if parts[0] == "gpu-logos" and len(parts) == 2:
            name = parts[1]
            if not re.match(r"^[a-z0-9_-]+\.(png|webp|svg)$", name, re.I):
                self._send_raw(404, b"", "text/plain; charset=utf-8")
                return
            static_parts = tuple(parts)
        elif len(parts) == 1 and re.match(r"^app-part[1-6]\.js$", parts[0], re.I):
            static_parts = ("admin", parts[0])
        elif (
            len(parts) == 3
            and parts[0] == "app-src"
            and parts[1] in ("part2", "part4")
            and re.match(r"^[a-z0-9-]+\.js$", parts[2], re.I)
        ):
            static_parts = ("admin", "app-src", parts[1], parts[2])
        elif len(parts) == 1 and re.match(r"^[a-z0-9_.-]+\.(js|css)$", parts[0], re.I):
            static_parts = ("admin", parts[0])
        else:
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        try:
            data = resources.files("fleet_server").joinpath("static", *static_parts).read_bytes()
        except OSError:
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        ext = Path(static_parts[-1]).suffix.lower()
        ct = {
            ".png": "image/png",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(ext, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _serve_theme_css(self) -> None:
        p = self._repo_root() / "kitchensink" / "css" / "forgesdlc-pack-minimal.css"
        if not p.is_file():
            self._send_raw(404, b"/* kitchensink theme not present in checkout */\n", "text/css; charset=utf-8")
            return
        try:
            data = p.read_bytes()
        except OSError:
            self._send_raw(404, b"", "text/css; charset=utf-8")
            return
        self._send_raw(200, data, "text/css; charset=utf-8")

    def _serve_kitchensink_asset(self, rel: str) -> None:
        """Serve read-only CSS/JS from the ``kitchensink`` submodule (css/ or js/ only)."""
        rel = rel.replace("\\", "/").strip("/")
        if not rel or ".." in rel.split("/"):
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        root = (self._repo_root() / "kitchensink").resolve()
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        if not target.is_file():
            self._send_raw(404, b"/* not found */\n", "text/css; charset=utf-8")
            return
        ext = target.suffix.lower()
        if ext == ".css":
            ct = "text/css; charset=utf-8"
        elif ext == ".js":
            ct = "application/javascript; charset=utf-8"
        else:
            self._send_raw(403, b"", "text/plain; charset=utf-8")
            return
        parts_lower = {p.lower() for p in target.parts}
        if "css" not in parts_lower and "js" not in parts_lower:
            self._send_raw(403, b"", "text/plain; charset=utf-8")
            return
        try:
            data = target.read_bytes()
        except OSError:
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        self._send_raw(200, data, ct)

    def _read_binary_body(self, max_len: int) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > max_len:
            return b""
        return self.rfile.read(n)

    def _read_json(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 4_000_000:
            return {}
        raw = self.rfile.read(n)
        try:
            o = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return o if isinstance(o, dict) else {}

    def _auth_ok(self) -> bool:
        if getattr(self.server, "loopback_bind_skips_auth", False):
            return True
        exp = getattr(self.server, "expected_token", "") or ""
        if not exp.strip():
            return True
        auth = str(self.headers.get("Authorization") or "")
        m = re.match(r"Bearer\s+(.+)", auth, re.I)
        got = (m.group(1) if m else "").strip()
        return got == exp.strip()

    def _send(self, code: int, body: dict[str, Any]) -> None:
        data = json_bytes(body)
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _browser_navigation(self) -> bool:
        """True when the request looks like a top-level document load (address bar), not fetch/XHR."""
        mode = (self.headers.get("Sec-Fetch-Mode") or "").lower()
        if mode == "navigate":
            return True
        dest = (self.headers.get("Sec-Fetch-Dest") or "").lower()
        return dest == "document"

    def _send_unauthorized(self) -> None:
        if self._browser_navigation():
            html = (
                "<!DOCTYPE html><html><head><meta charset=\"utf-8\"/>"
                "<title>Fleet — sign in</title></head><body style=\"font-family:system-ui;padding:1.5rem;max-width:40rem\">"
                "<h1>Authorization required</h1>"
                "<p>This URL is a JSON API. Browsers do not send your Fleet bearer token here.</p>"
                "<p>Open the <strong>admin dashboard</strong> (works without a token when the server binds only to "
                "<code>127.0.0.1</code> / <code>localhost</code>):</p>"
                "<p><a href=\"/admin/\">/admin/</a></p>"
                "<p style=\"opacity:.75;font-size:.9rem\">API clients: send <code>Authorization: Bearer …</code> "
                "and <code>Accept: application/json</code>.</p>"
                "</body></html>"
            ).encode("utf-8")
            self._send_raw(401, html, "text/html; charset=utf-8")
            return
        self._send(401, {"ok": False, "error": "unauthorized"})

