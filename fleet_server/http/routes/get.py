"""HTTP GET routes."""

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


from fleet_server.http.base import FleetHandlerBase


class GetRoutesMixin:
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
        mb = re.match(r"^/v1/jobs/([^/]+)/workspace-worker-bundle$", path)
        if mb:
            jid = mb.group(1)
            tok = (self.headers.get("X-Workspace-Worker-Token") or "").strip()
            if not tok:
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            conn = store.connect(self.server.db_path)
            try:
                row, err = store.authenticate_workspace_worker_bridge(conn, jid, tok)
            finally:
                conn.close()
            if err == "not_found":
                self._send(404, {"ok": False, "error": "not_found"})
                return
            if err or row is None:
                code = 403 if err == "forbidden" else 401
                self._send(code, {"ok": False, "error": err or "unauthorized"})
                return
            meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            bundle = meta.get("workspace_worker_bundle")
            if not isinstance(bundle, dict):
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "bundle_missing",
                        "detail": "meta.workspace_worker_bundle not set for this job",
                    },
                )
                return
            argv_b = bundle.get("argv")
            if not isinstance(argv_b, list) or not all(isinstance(x, str) for x in argv_b):
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "invalid_bundle",
                        "detail": "workspace_worker_bundle.argv must be list[str]",
                    },
                )
                return
            self._send(200, {"ok": True, "argv": argv_b, "cwd": str(bundle.get("cwd") or "")})
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
                data_dir_h = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
                orch_h = container_layout.orchestration_metrics_snapshot(data_dir_h, conn)
                try:
                    store.maybe_record_telemetry_sample(conn, self.server.db_path, snap, orch_h)
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
                        "server_version": FleetHandlerBase.server_version,
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
                qsnap = parse_qs(urlparse(self.path).query)

                def _snap_int(name: str, default: int, lo: int, hi: int) -> int:
                    raw = (qsnap.get(name) or [str(default)])[0].strip()
                    try:
                        v = int(raw)
                    except (TypeError, ValueError):
                        v = default
                    return max(lo, min(hi, v))

                jobs_limit = _snap_int("jobs_limit", 10, 1, 50)
                jobs_offset = _snap_int("jobs_offset", 0, 0, 500_000)
                jobs_total = store.count_jobs(conn)
                if jobs_total > 0:
                    max_off = max(0, ((jobs_total - 1) // jobs_limit) * jobs_limit)
                    jobs_offset = min(jobs_offset, max_off)
                else:
                    jobs_offset = 0
                recent = store.list_jobs_summary(conn, limit=jobs_limit, offset=jobs_offset)
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
                orch_snap = container_layout.orchestration_metrics_snapshot(data_dir, conn)
                integrations["orchestration"] = orch_snap
                host_snap = host_stats.snapshot()
                host_snap["thermal_llm_advisory"] = thermal_llm_policy.build(host_snap)
                body: dict[str, Any] = {
                    "ok": True,
                    "meta": {
                        "auth_enforced": token_set and not skip,
                        "server_version": FleetHandlerBase.server_version,
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
                    "jobs_recent_total": jobs_total,
                    "jobs_recent_limit": jobs_limit,
                    "jobs_recent_offset": jobs_offset,
                    "active_workers": runner.list_active_workers(self.server.db_path),
                }
                try:
                    store.maybe_record_telemetry_sample(conn, self.server.db_path, host_snap, orch_snap)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    pass
                try:
                    body["meta"]["energy_ledger_kwh"] = store.get_energy_ledger(conn)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    body["meta"]["energy_ledger_kwh"] = None
                try:
                    body["meta"]["cooldown_summary"] = store.cooldown_summary_presets(conn)
                except (OSError, RuntimeError, TypeError, ValueError, sqlite3.Error):
                    body["meta"]["cooldown_summary"] = {}
                body["meta"]["self_update"] = self_update.self_update_meta(self._repo_root())
                self._send(200, body)
            finally:
                conn.close()
            return
        if path == "/v1/cooldown-summary":
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
            conn = store.connect(self.server.db_path)
            try:
                try:
                    payload = store.cooldown_summary_payload(conn, period=period_raw)
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
                self._send(200, payload)
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
        if path == "/v1/container-templates/status":
            self._send(200, container_templates.status_api_payload(data_dir))
            return
        if path == "/v1/container-templates":
            self._send(200, container_templates.templates_api_payload(data_dir))
            return
        if path == "/v1/container-templates/resolve":
            q = parse_qs(urlparse(self.path).query)
            raw_req = q.get("requirements") or []
            ids: list[str] = []
            for part in raw_req:
                if not part:
                    continue
                ids.extend([x.strip().lower() for x in str(part).split(",") if x.strip()])
            build_if_missing = container_templates.parse_build_if_missing_query(q)
            payload = container_templates.resolve_api_payload(
                data_dir, ids, build_if_missing=build_if_missing
            )
            code = 200 if payload.get("ok") else 400
            self._send(code, payload)
            return
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
            meta_out = dict(row.get("meta") or {}) if isinstance(row.get("meta"), dict) else {}
            if "workspace_worker_token" in meta_out:
                meta_out["workspace_worker_token"] = ""
            self._send(
                200,
                {
                    "ok": True,
                    "id": row["id"],
                    "kind": row.get("kind"),
                    "status": row["status"],
                    "session_id": row.get("session_id") or "",
                    "argv": row.get("argv") if isinstance(row.get("argv"), list) else [],
                    "meta": meta_out,
                    "stdout": row.get("stdout") or "",
                    "stderr": row.get("stderr") or "",
                    "exit_code": row.get("exit_code"),
                    "container_id": row.get("container_id"),
                    "created": row.get("created"),
                    "updated": row.get("updated"),
                    "worker_progress": row.get("worker_progress")
                    if isinstance(row.get("worker_progress"), dict)
                    else None,
                    "worker_result": row.get("worker_result")
                    if isinstance(row.get("worker_result"), dict)
                    else None,
                },
            )
            return
        self._send(404, {"ok": False, "error": "not_found"})


