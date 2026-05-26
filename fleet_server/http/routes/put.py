"""HTTP PUT routes."""

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


class PutRoutesMixin:
    def do_PUT(self) -> None:
        if not self._auth_ok():
            self._send_unauthorized()
            return
        path = urlparse(self.path).path
        data_dir = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        m_job_ws = re.match(r"^/v1/jobs/([^/]+)/workspace$", path)
        if m_job_ws:
            jid = m_job_ws.group(1)
            max_up = workspace_bundle.max_upload_bytes()
            raw = self._read_binary_body(max_up)
            if len(raw) == 0:
                self._send(
                    400,
                    {"ok": False, "error": "invalid_body", "detail": "empty or oversized body (check Content-Length)"},
                )
                return
            body_sha = hashlib.sha256(raw).hexdigest()
            hdr_sha = (self.headers.get("X-Workspace-Archive-Sha256") or "").strip().lower()
            if hdr_sha and hdr_sha != body_sha:
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "archive_sha256_mismatch",
                        "detail": "X-Workspace-Archive-Sha256 does not match request body digest",
                    },
                )
                return
            conn = store.connect(self.server.db_path)
            try:
                row = store.get_job(conn, jid)
                if row is None:
                    self._send(404, {"ok": False, "error": "not_found"})
                    return
                if str(row.get("status") or "") != "queued":
                    self._send(409, {"ok": False, "error": "job_not_queued"})
                    return
                meta = dict(row.get("meta") or {})
                if not meta.get("workspace_upload_required"):
                    self._send(400, {"ok": False, "error": "workspace_not_requested"})
                    return
                if meta.get("workspace_state") != "pending_upload":
                    self._send(409, {"ok": False, "error": "workspace_already_uploaded"})
                    return
                prof = workspace_bundle.profile_for_meta(meta)
                manifest_required = bool(meta.get("workspace_manifest_required"))
                unc, sha256_hex, err, m_ver, m_schema = workspace_bundle.extract_archive_simple(
                    raw,
                    data_dir=data_dir,
                    job_id=jid,
                    profile=prof,
                    manifest_required=manifest_required,
                )
                if err:
                    self._send(400, {"ok": False, "error": "extract_failed", "detail": err})
                    return
                patch = {
                    "workspace_state": "ready",
                    "workspace_sha256": sha256_hex,
                    "workspace_upload_bytes": len(raw),
                    "workspace_uncompressed_bytes": unc,
                    "workspace_manifest_files_verified": m_ver,
                }
                if m_schema is not None:
                    patch["workspace_manifest_schema_version"] = m_schema
                store.merge_job_meta(conn, jid, patch)
            finally:
                conn.close()
            runner.spawn(self.server.db_path, jid)
            self._send(
                200,
                {
                    "ok": True,
                    "id": jid,
                    "workspace_state": "ready",
                    "workspace_sha256": body_sha,
                    "workspace_upload_bytes": len(raw),
                    "workspace_uncompressed_bytes": unc,
                    "manifest_files_verified": m_ver,
                    "manifest_schema_version": m_schema,
                },
            )
            return

        m_tpl_pkg = re.match(r"^/v1/container-templates/([^/]+)/package$", path)
        if m_tpl_pkg:
            rid_raw = m_tpl_pkg.group(1)
            max_up = container_templates.max_template_package_upload_bytes()
            raw = self._read_binary_body(max_up)
            if len(raw) == 0:
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "invalid_body",
                        "detail": "empty or oversized body (check Content-Length against FLEET_TEMPLATE_PACKAGE_UPLOAD_MAX_BYTES)",
                    },
                )
                return
            body_sha = hashlib.sha256(raw).hexdigest()
            hdr_sha = (self.headers.get("X-Template-Package-Sha256") or "").strip().lower()
            if hdr_sha and hdr_sha != body_sha:
                self._send(
                    400,
                    {
                        "ok": False,
                        "error": "archive_sha256_mismatch",
                        "detail": "X-Template-Package-Sha256 does not match request body digest",
                    },
                )
                return
            q = parse_qs(urlparse(self.path).query)
            title = (q.get("title") or [""])[0]
            notes = (q.get("notes") or [""])[0]
            replace_raw = (q.get("replace") or ["1"])[0].strip().lower()
            replace = replace_raw not in ("0", "false", "no")
            out = container_templates.apply_requirement_template_package(
                data_dir,
                rid_raw,
                raw,
                title=title,
                notes=notes,
                replace=replace,
            )
            if not out.get("ok"):
                err = str(out.get("error") or "failed")
                code = 409 if err == "template_exists" else 400
                self._send(code, out)
                return
            self._send(200, out)
            return

        body = self._read_json()
        data_dir_p = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        container_layout.ensure_layout(data_dir_p)

        if path == "/v1/container-types":
            try:
                container_layout.save_types_document(data_dir_p, body)
            except ValueError as ex:
                self._send(400, {"ok": False, "error": str(ex)[:800]})
                return
            self._send(200, container_layout.types_api_payload(data_dir_p))
            return
        if path == "/v1/container-templates":
            try:
                container_templates.save_requirement_templates(data_dir_p, body)
            except ValueError as ex:
                self._send(400, {"ok": False, "error": str(ex)[:800]})
                return
            self._send(200, container_templates.templates_api_payload(data_dir_p))
            return
        m_ct = re.match(r"^/v1/container-types/([^/]+)$", path)
        if m_ct:
            try:
                row = container_layout.update_type_row(data_dir_p, m_ct.group(1), body)
            except FileNotFoundError:
                self._send(404, {"ok": False, "error": "not_found"})
                return
            except ValueError as ex:
                self._send(400, {"ok": False, "error": str(ex)[:800]})
                return
            self._send(200, {"ok": True, "type": row})
            return
        m = re.match(r"^/v1/container-services/([^/]+)$", path)
        if not m:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        try:
            rec = container_layout.update_service(data_dir_p, m.group(1), body)
        except FileNotFoundError:
            self._send(404, {"ok": False, "error": "not_found"})
            return
        except (ValueError, OSError) as ex:
            self._send(400, {"ok": False, "error": "update_failed", "detail": str(ex)[:1200]})
            return
        self._send(200, {"ok": True, "service": rec})


