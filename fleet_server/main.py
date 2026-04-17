"""CLI entry: ``python -m fleet_server``."""

from __future__ import annotations

import argparse
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fleet_server import host_stats, runner, store


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


class FleetHandler(BaseHTTPRequestHandler):
    server_version = "forge-fleet/0.1"
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
            data = resources.files("fleet_server").joinpath("static/admin.html").read_bytes()
        except OSError:
            self._send_raw(500, b"admin bundle missing", "text/plain; charset=utf-8")
            return
        self._send_raw(200, data, "text/html; charset=utf-8")

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
        exp = getattr(self.server, "expected_token", "") or ""
        if not exp.strip():
            return True
        auth = str(self.headers.get("Authorization") or "")
        m = re.match(r"Bearer\s+(.+)", auth, re.I)
        got = (m.group(1) if m else "").strip()
        return got == exp.strip()

    def _send(self, code: int, body: dict[str, Any]) -> None:
        data = _json_bytes(body)
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
                "<p>Open the <strong>admin dashboard</strong> instead, then paste the same token you use for Lenses / "
                "<code>FLEET_BEARER_TOKEN</code>:</p>"
                "<p><a href=\"/admin/\">/admin/</a></p>"
                "<p style=\"opacity:.75;font-size:.9rem\">API clients: send <code>Authorization: Bearer …</code> "
                "and <code>Accept: application/json</code>.</p>"
                "</body></html>"
            ).encode("utf-8")
            self._send_raw(401, html, "text/html; charset=utf-8")
            return
        self._send(401, {"ok": False, "error": "unauthorized"})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/admin":
            self.send_response(302)
            self.send_header("Location", "/admin/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/admin/":
            self._serve_admin_shell()
            return
        if path == "/admin/theme.css":
            self._serve_theme_css()
            return
        if not self._auth_ok():
            self._send_unauthorized()
            return
        if path == "/v1/health":
            self._send(200, {"ok": True, "service": "forge-fleet"})
            return
        if path == "/v1/admin/snapshot":
            conn = store.connect(self.server.db_path)
            try:
                by_status = store.count_jobs_by_status(conn)
                recent = store.list_jobs_summary(conn, limit=150)
            finally:
                conn.close()
            body: dict[str, Any] = {
                "ok": True,
                "host": host_stats.snapshot(),
                "jobs_by_status": by_status,
                "jobs_recent": recent,
                "active_workers": runner.list_active_workers(self.server.db_path),
            }
            self._send(200, body)
            return
        m = re.match(r"^/v1/jobs/([^/]+)$", path)
        if m:
            jid = m.group(1)
            conn = store.connect(self.server.db_path)
            try:
                row = store.get_job(conn, jid)
            finally:
                conn.close()
            if row is None:
                self._send(404, {"ok": False, "error": "not_found"})
                return
            self._send(
                200,
                {
                    "ok": True,
                    "id": row["id"],
                    "status": row["status"],
                    "stdout": row.get("stdout") or "",
                    "stderr": row.get("stderr") or "",
                    "exit_code": row.get("exit_code"),
                    "container_id": row.get("container_id"),
                },
            )
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if not self._auth_ok():
            self._send_unauthorized()
            return
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/v1/jobs":
            kind = str(body.get("kind") or "").strip()
            argv = body.get("argv")
            if kind != "docker_argv" or not isinstance(argv, list):
                self._send(400, {"ok": False, "error": "invalid_body"})
                return
            session_id = str(body.get("session_id") or "")
            meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
            conn = store.connect(self.server.db_path)
            try:
                jid = store.insert_job(conn, kind=kind, argv=argv, session_id=session_id, meta=meta)
            finally:
                conn.close()
            runner.spawn(self.server.db_path, jid)
            self._send(201, {"ok": True, "id": jid, "status": "queued"})
            return
        m = re.match(r"^/v1/jobs/([^/]+)/cancel$", path)
        if m:
            jid = m.group(1)
            ok = runner.cancel(jid)
            conn = store.connect(self.server.db_path)
            try:
                row = store.get_job(conn, jid)
                if row and row["status"] == "running":
                    store.update_job(conn, jid, status="cancelled", stderr=(row.get("stderr") or "") + "\ncancel_requested")
            finally:
                conn.close()
            self._send(200, {"ok": True, "cancelled": ok})
            return
        self._send(404, {"ok": False, "error": "not_found"})


def main() -> None:
    ap = argparse.ArgumentParser(description="Forge Fleet HTTP server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18765)
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("FLEET_DATA_DIR") or ".fleet-data"),
        help="Directory for fleet.sqlite",
    )
    args = ap.parse_args()
    data_dir: Path = args.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "fleet.sqlite"
    token = str(os.environ.get("FLEET_BEARER_TOKEN") or "").strip()

    conn = store.connect(db_path)
    conn.close()

    httpd = ThreadingHTTPServer((args.host, args.port), FleetHandler)
    httpd.db_path = db_path
    httpd.expected_token = token
    print(f"[fleet] http://{args.host}:{args.port}/  db={db_path} auth={'bearer' if token else 'disabled'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
