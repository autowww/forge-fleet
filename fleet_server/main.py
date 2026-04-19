"""CLI entry: ``python -m fleet_server``."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import re
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fleet_server import (
    container_layout,
    forge_llm_service,
    host_stats,
    runner,
    self_update,
    store,
    telemetry_periods,
    templates_catalog,
    versioning,
)
from fleet_server.test_fleet import spawn_test_fleet


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _loopback_bind_only(host: str) -> bool:
    """True when the listen address accepts only same-machine connections (no LAN/WAN socket)."""
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost")


class FleetHandler(BaseHTTPRequestHandler):
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
            data = resources.files("fleet_server").joinpath("static/admin.html").read_bytes()
        except OSError:
            self._send_raw(500, b"admin bundle missing", "text/plain; charset=utf-8")
            return
        self._send_raw(200, data, "text/html; charset=utf-8")

    def _serve_admin_packaged_static(self, rel: str) -> None:
        """PNG etc. shipped under ``fleet_server/static/`` (e.g. GPU logos for ``/admin/``)."""
        rel = rel.replace("\\", "/").strip("/")
        if not rel or ".." in rel.split("/"):
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        parts = rel.split("/")
        if parts[0] != "gpu-logos" or len(parts) != 2:
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        name = parts[1]
        if not re.match(r"^[a-z0-9_-]+\.(png|webp|svg)$", name, re.I):
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        try:
            data = resources.files("fleet_server").joinpath("static", *parts).read_bytes()
        except OSError:
            self._send_raw(404, b"", "text/plain; charset=utf-8")
            return
        ext = Path(name).suffix.lower()
        ct = {".png": "image/png", ".webp": "image/webp", ".svg": "image/svg+xml"}.get(ext, "application/octet-stream")
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
        mks = re.match(r"^/admin/ks/(.+)$", path)
        if mks:
            self._serve_kitchensink_asset(mks.group(1))
            return
        mst = re.match(r"^/admin/static/(.+)$", path)
        if mst:
            self._serve_admin_packaged_static(mst.group(1))
            return
        if not self._auth_ok():
            self._send_unauthorized()
            return
        if path == "/v1/version":
            conn = store.connect(self.server.db_path)
            try:
                row = store.get_fleet_version_row(conn)
            finally:
                conn.close()
            self._send(
                200,
                versioning.version_api_payload(
                    db_schema_version=int(row["db_schema_version"]),
                    db_package_semver=str(row.get("package_semver") or "") or None,
                ),
            )
            return
        if path == "/v1/templates":
            self._send(200, templates_catalog.templates_payload())
            return
        if path == "/v1/health":
            token_set = bool(str(getattr(self.server, "expected_token", "") or "").strip())
            skip = bool(getattr(self.server, "loopback_bind_skips_auth", False))
            snap = host_stats.snapshot()
            mem = snap.get("memory") if isinstance(snap.get("memory"), dict) else {}
            mem_pct = mem.get("used_pct") if isinstance(mem, dict) else None
            cpu_pct = snap.get("cpu_usage_pct")
            conn = store.connect(self.server.db_path)
            try:
                vrow = store.get_fleet_version_row(conn)
                el: dict[str, Any] = {}
                try:
                    store.maybe_record_telemetry_sample(conn, self.server.db_path, snap)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    pass
                try:
                    el = store.get_energy_ledger(conn)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    el = {}
            finally:
                conn.close()
            self._send(
                200,
                {
                    "ok": True,
                    "service": "forge-fleet",
                    "auth_enforced": token_set and not skip,
                    "version": {
                        "package_semver": versioning.package_semver(),
                        "db_schema_version": int(vrow["db_schema_version"]),
                        "template_lib_version": versioning.FLEET_TEMPLATE_LIB_VERSION,
                        "server_version": FleetHandler.server_version,
                    },
                    "host": {
                        "cpu_usage_pct": cpu_pct,
                        "memory_used_pct": mem_pct,
                        "loadavg_1m": (snap.get("loadavg") or [None])[0]
                        if isinstance(snap.get("loadavg"), list) and snap.get("loadavg")
                        else None,
                        "energy_ledger_kwh": el or None,
                    },
                },
            )
            return
        if path == "/v1/admin/snapshot":
            conn = store.connect(self.server.db_path)
            try:
                by_status = store.count_jobs_by_status(conn)
                recent = store.list_jobs_summary(conn, limit=150)
                core_s = store.sum_accounted_core_seconds(conn)
                vrow = store.get_fleet_version_row(conn)
                token_set = bool(str(getattr(self.server, "expected_token", "") or "").strip())
                skip = bool(getattr(self.server, "loopback_bind_skips_auth", False))
                fleet_epoch = float(getattr(self.server, "fleet_started_epoch", time.time()))
                total_jobs = sum(int(n) for n in by_status.values()) if by_status else 0
                forge_console = str(os.environ.get("FLEET_FORGE_CONSOLE_URL") or "").strip().rstrip("/")
                data_dir = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
                container_layout.ensure_layout(data_dir)
                types_doc = container_layout.load_types(data_dir)
                llm_root_hint = str(os.environ.get("FLEET_FORGE_LLM_ROOT") or "").strip()
                integrations: dict[str, Any] = {
                    "forge_console_url": forge_console or None,
                    "suggested_forge_llm_compose_root": llm_root_hint or None,
                    "container_layout": container_layout.layout_paths_payload(data_dir),
                    "container_types_version": types_doc.get("version"),
                    "forge_llm_services": container_layout.services_status_snapshot(data_dir),
                }
                host_snap = host_stats.snapshot()
                body: dict[str, Any] = {
                    "ok": True,
                    "meta": {
                        "auth_enforced": token_set and not skip,
                        "server_version": FleetHandler.server_version,
                        "fleet_data_dir": str(getattr(self.server, "fleet_data_dir", "") or ""),
                        "sqlite_path": str(self.server.db_path),
                        "listen_host": str(getattr(self.server, "listen_host", "") or ""),
                        "jobs_total": total_jobs,
                        "version": {
                            "package_semver": versioning.package_semver(),
                            "db_recorded_package_semver": str(vrow.get("package_semver") or ""),
                            "db_schema_version": int(vrow["db_schema_version"]),
                            "template_lib_version": versioning.FLEET_TEMPLATE_LIB_VERSION,
                            "git_sha": versioning.git_sha_short() or None,
                        },
                        "integrations": integrations,
                    },
                    "host": host_snap,
                    "node": {
                        "fleet_started_utc": getattr(self.server, "fleet_started_utc", ""),
                        "fleet_started_epoch": fleet_epoch,
                        "fleet_uptime_s": round(time.time() - fleet_epoch, 3),
                        "core_hours_1c": round(core_s / 3600.0, 5),
                        "core_seconds_1c": round(core_s, 3),
                    },
                    "jobs_by_status": by_status,
                    "jobs_recent": recent,
                    "active_workers": runner.list_active_workers(self.server.db_path),
                }
                try:
                    store.maybe_record_telemetry_sample(conn, self.server.db_path, host_snap)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    pass
                try:
                    body["meta"]["energy_ledger_kwh"] = store.get_energy_ledger(conn)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    body["meta"]["energy_ledger_kwh"] = None
                body["meta"]["self_update"] = self_update.self_update_meta(self._repo_root())
                self._send(200, body)
            finally:
                conn.close()
            return
        if path == "/v1/telemetry":
            q = parse_qs(urlparse(self.path).query)
            period_raw = (q.get("period") or [""])[0].strip()
            if not period_raw:
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "bad_request",
                        "detail": "Missing required query parameter period.",
                        "periods": list(telemetry_periods.ALL_PERIODS),
                        "aliases": dict(telemetry_periods.PERIOD_ALIASES),
                    },
                )
                return
            try:
                lim_raw = (q.get("limit") or ["200000"])[0]
                limit = int(lim_raw)
            except (ValueError, IndexError):
                limit = 200_000
            conn = store.connect(self.server.db_path)
            try:
                t_min, t_max, _n = store.telemetry_time_bounds(conn)
                period_key = telemetry_periods.PERIOD_ALIASES.get(period_raw, period_raw)
                try:
                    t0, t1 = telemetry_periods.resolve_period_window(
                        period_key,
                        first_sample_ts=t_min,
                    )
                except ValueError as ex:
                    self._send(
                        400,
                        {
                            "ok": False,
                            "error": "bad_request",
                            "detail": str(ex),
                            "periods": list(telemetry_periods.ALL_PERIODS),
                            "aliases": dict(telemetry_periods.PERIOD_ALIASES),
                        },
                    )
                    return
                rows, truncated = store.list_telemetry_samples(conn, t0=t0, t1=t1, limit=limit)
                try:
                    el = store.get_energy_ledger(conn)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    el = None
                self._send(
                    200,
                    {
                        "ok": True,
                        "period": period_key,
                        "period_requested": period_raw,
                        "timezone": "UTC",
                        "window": {"start_epoch": t0, "end_epoch": t1},
                        "samples": rows,
                        "count": len(rows),
                        "truncated": truncated,
                        "store_bounds": {"first_ts": t_min, "last_ts": t_max},
                        "energy_ledger_kwh": el,
                    },
                )
            finally:
                conn.close()
            return
        data_dir = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        container_layout.ensure_layout(data_dir)
        if path == "/v1/container-types":
            self._send(200, container_layout.types_api_payload(data_dir))
            return
        if path == "/v1/container-services":
            rows: list[dict[str, Any]] = []
            for rec in container_layout.list_service_records(data_dir):
                row = dict(rec)
                if str(row.get("type_id")) == "forge_llm":
                    row["status"] = forge_llm_service.status_for_record(rec)
                rows.append(row)
            self._send(
                200,
                {"ok": True, "services": rows, "paths": container_layout.layout_paths_payload(data_dir)},
            )
            return
        mcs = re.match(r"^/v1/container-services/([^/]+)$", path)
        if mcs:
            sid = mcs.group(1)
            rec = container_layout.read_service(data_dir, sid)
            if rec is None:
                self._send(404, {"ok": False, "error": "not_found"})
                return
            out = dict(rec)
            if str(out.get("type_id")) == "forge_llm":
                out["status"] = forge_llm_service.status_for_record(rec)
            self._send(200, {"ok": True, "service": out, "paths": container_layout.layout_paths_payload(data_dir)})
            return
        if path == "/v1/services/forge-llm":
            sid = container_layout.pick_primary_forge_llm_service_id(data_dir)
            if sid is None:
                self._send(
                    200,
                    {
                        "ok": True,
                        "configured": False,
                        "detail": "No forge_llm service under etc/services/. Use POST /v1/container-services or set FLEET_FORGE_LLM_ROOT for auto-migration.",
                    },
                )
                return
            rec = container_layout.read_service(data_dir, sid)
            if rec is None:
                self._send(500, {"ok": False, "error": "service_missing"})
                return
            st = forge_llm_service.status_for_record(rec)
            self._send(200, {**st, "configured": True, "legacy_endpoint": True})
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
            if str(meta.get("container_class") or "").strip().lower() == "empty":
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "empty_container_class_not_supported",
                        "detail": "container_class empty is internal-only and cannot be queued via /v1/jobs.",
                    },
                )
                return
            conn = store.connect(self.server.db_path)
            try:
                jid = store.insert_job(conn, kind=kind, argv=argv, session_id=session_id, meta=meta)
            finally:
                conn.close()
            runner.spawn(self.server.db_path, jid)
            self._send(201, {"ok": True, "id": jid, "status": "queued"})
            return
        if path == "/v1/containers/dispose":
            cid = str(body.get("container_id") or "").strip()
            ok, detail = runner.dispose_container(cid)
            self._send(200 if ok else 400, {"ok": ok, "container_id": cid, "detail": detail})
            return
        if path == "/v1/admin/test-fleet":
            try:
                n = int(body.get("count", 5))
            except (TypeError, ValueError):
                n = 5
            try:
                out = spawn_test_fleet(self.server.db_path, count=n)
                self._send(200, out)
            except FileNotFoundError as ex:
                self._send(500, {"ok": False, "error": "probe_script_missing", "detail": str(ex)})
            except Exception as ex:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "test_fleet_failed", "detail": str(ex)[:800]})
            return
        if path == "/v1/admin/git-self-update":
            out = self_update.run_git_self_update(self._repo_root())
            code = 200 if out.get("ok") else 400
            self._send(code, out)
            return
        data_dir_p = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        container_layout.ensure_layout(data_dir_p)

        def _forge_llm_record_or_503() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            sid = container_layout.pick_primary_forge_llm_service_id(data_dir_p)
            if sid is None:
                return None, {
                    "ok": False,
                    "error": "forge_llm_not_configured",
                    "detail": "Add a forge_llm service (POST /v1/container-services) or set FLEET_FORGE_LLM_ROOT for auto-migration.",
                }
            rec = container_layout.read_service(data_dir_p, sid)
            if rec is None or str(rec.get("type_id")) != "forge_llm":
                return None, {"ok": False, "error": "forge_llm_service_invalid"}
            return rec, None

        m_start = re.match(r"^/v1/container-services/([^/]+)/start$", path)
        if m_start:
            sid = m_start.group(1)
            rec = container_layout.read_service(data_dir_p, sid)
            if rec is None:
                self._send(404, {"ok": False, "error": "not_found"})
                return
            if str(rec.get("type_id")) != "forge_llm":
                self._send(400, {"ok": False, "error": "unsupported_service_type"})
                return
            try:
                out = forge_llm_service.start_for_record(rec)
            except (ValueError, FileNotFoundError) as ex:
                self._send(400, {"ok": False, "error": "invalid_service_record", "detail": str(ex)[:800]})
                return
            code = 200 if out.get("ok") else 502
            merged = dict(out)
            merged["ok"] = bool(out.get("ok"))
            self._send(code, merged)
            return
        m_stop = re.match(r"^/v1/container-services/([^/]+)/stop$", path)
        if m_stop:
            sid = m_stop.group(1)
            rec = container_layout.read_service(data_dir_p, sid)
            if rec is None:
                self._send(404, {"ok": False, "error": "not_found"})
                return
            if str(rec.get("type_id")) != "forge_llm":
                self._send(400, {"ok": False, "error": "unsupported_service_type"})
                return
            try:
                out = forge_llm_service.stop_for_record(rec)
            except (ValueError, FileNotFoundError) as ex:
                self._send(400, {"ok": False, "error": "invalid_service_record", "detail": str(ex)[:800]})
                return
            code = 200 if out.get("ok") else 502
            merged = dict(out)
            merged["ok"] = bool(out.get("ok"))
            self._send(code, merged)
            return
        if path == "/v1/container-services":
            try:
                raw_sid = str(body.get("id") or "").strip().lower()
                if raw_sid:
                    service_id = raw_sid
                else:
                    service_id = container_layout.allocate_forge_llm_service_id(data_dir_p)
                rec = container_layout.upsert_service(
                    data_dir_p,
                    service_id=service_id,
                    type_id=str(body.get("type_id") or "").strip(),
                    compose_root=str(body.get("compose_root") or "").strip(),
                    compose_files=body.get("compose_files") if isinstance(body.get("compose_files"), list) else [],
                    label=body["label"] if "label" in body else None,
                    allow_replace=False,
                )
            except ValueError as ex:
                self._send(400, {"ok": False, "error": str(ex)})
                return
            except FileNotFoundError as ex:
                self._send(400, {"ok": False, "error": "compose_file_missing", "detail": str(ex)})
                return
            self._send(201, {"ok": True, "service": rec})
            return
        if path == "/v1/services/forge-llm/start":
            rec, err = _forge_llm_record_or_503()
            if rec is None:
                self._send(503, err or {"ok": False, "error": "forge_llm_not_configured"})
                return
            try:
                out = forge_llm_service.start_for_record(rec)
            except (ValueError, FileNotFoundError) as ex:
                self._send(400, {"ok": False, "error": "invalid_service_record", "detail": str(ex)[:800]})
                return
            code = 200 if out.get("ok") else 502
            merged = dict(out)
            merged["ok"] = bool(out.get("ok"))
            self._send(code, merged)
            return
        if path == "/v1/services/forge-llm/stop":
            rec, err = _forge_llm_record_or_503()
            if rec is None:
                self._send(503, err or {"ok": False, "error": "forge_llm_not_configured"})
                return
            try:
                out = forge_llm_service.stop_for_record(rec)
            except (ValueError, FileNotFoundError) as ex:
                self._send(400, {"ok": False, "error": "invalid_service_record", "detail": str(ex)[:800]})
                return
            code = 200 if out.get("ok") else 502
            merged = dict(out)
            merged["ok"] = bool(out.get("ok"))
            self._send(code, merged)
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

    def do_PUT(self) -> None:
        if not self._auth_ok():
            self._send_unauthorized()
            return
        path = urlparse(self.path).path
        body = self._read_json()
        m = re.match(r"^/v1/container-services/([^/]+)$", path)
        if not m:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        data_dir_p = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        container_layout.ensure_layout(data_dir_p)
        try:
            rec = container_layout.update_service(data_dir_p, m.group(1), body)
        except FileNotFoundError:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        except (ValueError, OSError) as ex:
            self._send(400, {"ok": False, "error": "update_failed", "detail": str(ex)[:1200]})
            return
        self._send(200, {"ok": True, "service": rec})

    def do_DELETE(self) -> None:
        if not self._auth_ok():
            self._send_unauthorized()
            return
        path = urlparse(self.path).path
        m = re.match(r"^/v1/container-services/([^/]+)$", path)
        if not m:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        data_dir_p = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        container_layout.ensure_layout(data_dir_p)
        ok, detail = container_layout.delete_service(data_dir_p, m.group(1))
        if not ok:
            if detail == "not_found":
                self._send(404, {"ok": False, "error": "not_found"})
            elif detail == "stop_service_first":
                self._send(409, {"ok": False, "error": detail})
            else:
                self._send(400, {"ok": False, "error": detail})
            return
        self._send(200, {"ok": True, "detail": detail})


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
    force_bearer = str(os.environ.get("FLEET_ENFORCE_BEARER") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    loopback_only = _loopback_bind_only(args.host)
    loopback_skips_auth = bool(token) and loopback_only and not force_bearer

    conn = store.connect(db_path)
    conn.close()
    container_layout.ensure_layout(data_dir)

    httpd = ThreadingHTTPServer((args.host, args.port), FleetHandler)
    httpd.db_path = db_path
    httpd.fleet_data_dir = str(data_dir)
    httpd.listen_host = str(args.host)
    httpd.expected_token = token
    httpd.loopback_bind_skips_auth = loopback_skips_auth
    httpd.fleet_started_epoch = time.time()
    httpd.fleet_started_utc = datetime.now(UTC).isoformat()
    if loopback_skips_auth:
        auth_note = "off (loopback bind — bearer not required; set FLEET_ENFORCE_BEARER=1 to force)"
    elif token:
        auth_note = "bearer"
    else:
        auth_note = "disabled (no FLEET_BEARER_TOKEN)"
    print(f"[fleet] http://{args.host}:{args.port}/  db={db_path} auth={auth_note}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
