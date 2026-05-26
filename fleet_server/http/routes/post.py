"""HTTP POST routes."""

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


class PostRoutesMixin:
    def do_POST(self) -> None:
        path = urlparse(self.path).path
        body = self._read_json()
        m_br = re.match(r"^/v1/jobs/([^/]+)/workspace-worker-(progress|complete)$", path)
        if m_br:
            jid = m_br.group(1)
            kind = m_br.group(2)
            tok = (self.headers.get("X-Workspace-Worker-Token") or "").strip()
            if not tok:
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            conn = store.connect(self.server.db_path)
            try:
                row, err = store.authenticate_workspace_worker_bridge(conn, jid, tok)
                if err == "not_found":
                    self._send(404, {"ok": False, "error": "not_found"})
                    return
                if err or row is None:
                    code = 403 if err == "forbidden" else 401
                    self._send(code, {"ok": False, "error": err or "unauthorized"})
                    return
                if kind == "progress":
                    store.merge_worker_progress(conn, jid, body)
                else:
                    store.set_worker_result(conn, jid, body)
            except ValueError:
                self._send(404, {"ok": False, "error": "not_found"})
                return
            finally:
                conn.close()
            self._send(200, {"ok": True})
            return
        if not self._auth_ok():
            self._send_unauthorized()
            return
        if path == "/v1/cooldown-events":
            raw_d = body.get("duration_s")
            try:
                dur = float(raw_d) if raw_d is not None else -1.0
            except (TypeError, ValueError):
                dur = -1.0
            if dur < 0 or dur != dur:
                self._send(400, {"ok": False, "error": "invalid_body", "detail": "duration_s must be a non-negative number"})
                return
            max_s_raw = str(os.environ.get("FLEET_COOLDOWN_EVENT_MAX_S") or "").strip()
            try:
                max_s = float(max_s_raw) if max_s_raw else 86400.0
            except ValueError:
                max_s = 86400.0
            if max_s <= 0:
                max_s = 86400.0
            accepted = min(dur, max_s)
            clamped = accepted < dur
            kind = str(body.get("kind") or "thermal_llm_guard").strip() or "thermal_llm_guard"
            meta = body.get("meta") if isinstance(body.get("meta"), dict) else None
            conn = store.connect(self.server.db_path)
            try:
                row_id = store.insert_cooldown_event(
                    conn,
                    duration_s=accepted,
                    kind=kind,
                    meta=meta,
                )
            except ValueError as ex:
                self._send(400, {"ok": False, "error": "invalid_body", "detail": str(ex)[:800]})
                return
            finally:
                conn.close()
            self._send(
                201,
                {
                    "ok": True,
                    "id": row_id,
                    "accepted_duration_s": round(accepted, 6),
                    "clamped": clamped,
                },
            )
            return
        if path == "/v1/jobs":
            kind = str(body.get("kind") or "").strip()
            argv = body.get("argv")
            if kind != "docker_argv" or not isinstance(argv, list):
                self._send(400, {"ok": False, "error": "invalid_body"})
                return
            session_id = str(body.get("session_id") or "")
            meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
            meta = dict(meta)
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
            if meta.get("use_fleet_template_image"):
                reqs_raw = meta.get("requirements")
                if not isinstance(reqs_raw, list) or not reqs_raw:
                    self._send(
                        400,
                        {
                            "ok": False,
                            "error": "invalid_body",
                            "detail": "meta.requirements must be a non-empty list when meta.use_fleet_template_image is set.",
                        },
                    )
                    return
                data_dir_tpl = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
                container_layout.ensure_layout(data_dir_tpl)
                req_ids = [str(x) for x in reqs_raw]
                build_if_missing = container_templates.meta_build_template_if_missing(meta)
                res = container_templates.resolve_api_payload(
                    data_dir_tpl, req_ids, build_if_missing=build_if_missing
                )
                if not res.get("ok") or not res.get("image"):
                    self._send(
                        400,
                        {
                            "ok": False,
                            "error": "template_resolve_failed",
                            "detail": res,
                        },
                    )
                    return
                argv = container_templates.inject_template_image_into_docker_argv(
                    list(argv), str(res["image"])
                )
            if meta.get("workspace_upload_required"):
                meta["workspace_state"] = "pending_upload"
            conn = store.connect(self.server.db_path)
            try:
                jid = store.insert_job(conn, kind=kind, argv=argv, session_id=session_id, meta=meta)
            finally:
                conn.close()
            if not meta.get("workspace_upload_required"):
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
        if path == "/v1/container-types":
            try:
                row = container_layout.add_type_row(data_dir_p, body)
            except ValueError as ex:
                self._send(400, {"ok": False, "error": str(ex)[:800]})
                return
            self._send(201, {"ok": True, "type": row})
            return
        if path == "/v1/container-templates/build":
            req_raw = body.get("requirement_ids")
            if not isinstance(req_raw, list):
                req_raw = body.get("requirements")
            if not isinstance(req_raw, list):
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "invalid_body",
                        "detail": "requirement_ids (or requirements) must be a list of requirement slugs.",
                    },
                )
                return
            ids = [str(x) for x in req_raw]
            out = container_templates.run_template_build(data_dir_p, ids)
            code = 200 if out.get("ok") else 400
            self._send(code, out)
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


