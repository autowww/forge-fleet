"""HTTP DELETE routes."""

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


class DeleteRoutesMixin:
    def do_DELETE(self) -> None:
        if not self._auth_ok():
            self._send_unauthorized()
            return
        path = urlparse(self.path).path
        data_dir_p = Path(str(getattr(self.server, "fleet_data_dir", ".") or ".")).resolve()
        container_layout.ensure_layout(data_dir_p)
        m_ct = re.match(r"^/v1/container-types/([^/]+)$", path)
        if m_ct:
            conn = store.connect(self.server.db_path)
            try:
                ok, detail = container_layout.delete_type_row(data_dir_p, m_ct.group(1), conn)
            finally:
                conn.close()
            if not ok:
                if detail == "not_found":
                    self._send(404, {"ok": False, "error": "not_found"})
                elif detail in ("reserved_type_id", "running_jobs_for_container_class", "services_referencing_type"):
                    self._send(409, {"ok": False, "error": detail})
                else:
                    self._send(400, {"ok": False, "error": detail})
                return
            self._send(200, {"ok": True, "detail": detail})
            return
        m = re.match(r"^/v1/container-services/([^/]+)$", path)
        if not m:
            self._send(404, {"ok": False, "error": "not_found"})
            return
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


