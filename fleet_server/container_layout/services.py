"""On-disk container **types** and **service** definitions under ``$FLEET_DATA_DIR/etc/``.

Layout (created at startup, same ``--data-dir`` as ``fleet.sqlite`` — matches
``install-user.sh`` / ``install-update.sh`` state directories):

- ``etc/containers/types.json`` — catalog: **categories** (MECE policy defaults) + **types**
  (each references ``category_id`` and inherits ``capabilities`` unless overridden).
- ``etc/services/<id>.json`` — one **managed** stack per file (today: ``forge_llm`` compose roots).

If ``FLEET_FORGE_LLM_ROOT`` is set and ``etc/services/`` is empty, a ``default.json``
service is written once so existing env-based installs keep working.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from fleet_server import container_templates, forge_llm_service, store

from fleet_server.container_layout.paths import (
    _write_json_atomic,
    effective_type_by_id,
    ensure_layout,
    service_file,
    services_dir,
)

_SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

_TYPE_ID_RE = _SERVICE_ID_RE

_CONTAINER_CLASS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")

_CAPABILITY_KEYS = ("admin_spawnable", "api_manage_services", "allow_docker_argv_jobs")

# Types that must never be removed via API (system contracts).
RESERVED_TYPE_IDS: frozenset[str] = frozenset({"empty"})


def validate_service_id(service_id: str) -> str:
    sid = str(service_id or "").strip().lower()
    if not _SERVICE_ID_RE.match(sid):
        raise ValueError("invalid_service_id")
    return sid


def allocate_forge_llm_service_id(data_dir: Path) -> str:
    """
    Pick a new service id for ``POST /v1/container-services`` when the client omits ``id``.

    Order: ``default``, ``lab``, then ``llm2`` … ``llm99`` for the first basename
    not already present under ``etc/services/*.json``.
    """
    ensure_layout(data_dir)
    sdir = services_dir(data_dir)
    candidates = ["default", "lab"] + [f"llm{n}" for n in range(2, 100)]
    for cand in candidates:
        sid = validate_service_id(cand)
        if not service_file(data_dir, sid).is_file():
            return sid
    raise ValueError("no_free_service_id")


def list_service_records(data_dir: Path) -> list[dict[str, Any]]:
    ensure_layout(data_dir)
    out: list[dict[str, Any]] = []
    for p in sorted(services_dir(data_dir).glob("*.json")):
        try:
            o = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(o, dict) and o.get("id"):
            out.append(o)
    out.sort(key=lambda r: str(r.get("id") or ""))
    return out


def read_service(data_dir: Path, service_id: str) -> dict[str, Any] | None:
    sid = validate_service_id(service_id)
    p = service_file(data_dir, sid)
    if not p.is_file():
        return None
    try:
        o = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return o if isinstance(o, dict) else None


def delete_service(data_dir: Path, service_id: str) -> tuple[bool, str]:
    sid = validate_service_id(service_id)
    rec = read_service(data_dir, sid)
    if rec is None:
        return False, "not_found"
    if rec.get("type_id") == "forge_llm":
        try:
            st = forge_llm_service.status_for_record(rec)
            if int(st.get("services_running") or 0) > 0:
                return False, "stop_service_first"
        except (ValueError, FileNotFoundError, OSError):
            pass
    p = service_file(data_dir, sid)
    try:
        p.unlink()
    except OSError as ex:
        return False, str(ex)[:400]
    return True, "removed"


def _validate_compose_root(path_str: str) -> Path:
    p = Path(path_str).expanduser().resolve()
    if not p.is_dir():
        raise ValueError("compose_root_not_a_directory")
    if not (p / "compose.yaml").is_file():
        raise ValueError("compose_yaml_missing")
    return p


def upsert_service(
    data_dir: Path,
    *,
    service_id: str,
    type_id: str,
    compose_root: str,
    compose_files: list[str] | None,
    label: str | None,
    allow_replace: bool,
) -> dict[str, Any]:
    ensure_layout(data_dir)
    sid = validate_service_id(service_id)
    eff = effective_type_by_id(data_dir, type_id)
    if eff is None:
        raise ValueError("unknown_type_id")
    caps = eff.get("effective_capabilities") if isinstance(eff.get("effective_capabilities"), dict) else {}
    if not bool(caps.get("api_manage_services")):
        raise ValueError("type_not_api_manageable")
    root = _validate_compose_root(compose_root)
    extras = [str(x) for x in (compose_files or [])]
    forge_llm_service.resolve_compose_files(root, extras)  # raises if invalid / missing files
    existing = read_service(data_dir, sid)
    if existing is not None and not allow_replace:
        raise ValueError("service_id_exists")
    label_out = ((label if label is not None else "") or "").strip() or sid
    rec: dict[str, Any] = {
        "version": 1,
        "id": sid,
        "type_id": type_id,
        "label": label_out,
        "compose_root": str(root),
        "compose_files": extras,
    }
    _write_json_atomic(service_file(data_dir, sid), rec)
    return rec


def update_service(
    data_dir: Path,
    service_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    existing = read_service(data_dir, validate_service_id(service_id))
    if existing is None:
        raise FileNotFoundError("not_found")
    type_id = str(body.get("type_id") or existing.get("type_id") or "").strip()
    compose_root = str(body.get("compose_root") or existing.get("compose_root") or "").strip()
    label = body.get("label") if "label" in body else existing.get("label")
    compose_files = body.get("compose_files") if "compose_files" in body else existing.get("compose_files")
    if not isinstance(compose_files, list):
        compose_files = []
    return upsert_service(
        data_dir,
        service_id=service_id,
        type_id=type_id,
        compose_root=compose_root,
        compose_files=[str(x) for x in compose_files],
        label=str(label) if label is not None else None,
        allow_replace=True,
    )


def orchestration_metrics_snapshot(data_dir: Path, conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Running workload counts for admin: compose services by ``type_id`` plus
    ``running`` jobs keyed by ``meta.container_class``.
    """
    by_type: dict[str, dict[str, Any]] = {}
    for rec in list_service_records(data_dir):
        tid = str(rec.get("type_id") or "").strip()
        if not tid:
            continue
        st = forge_llm_service.status_for_record(rec)
        sr = st.get("services_running")
        stt = st.get("services_total")
        try:
            n_run = int(sr) if sr is not None and not isinstance(sr, bool) else 0
        except (TypeError, ValueError):
            n_run = 0
        try:
            n_tot = int(stt) if stt is not None and not isinstance(stt, bool) else 0
        except (TypeError, ValueError):
            n_tot = 0
        if tid not in by_type:
            by_type[tid] = {
                "services_running": 0,
                "services_total": 0,
                "ps_ok_any": False,
            }
        by_type[tid]["services_running"] += n_run
        by_type[tid]["services_total"] += n_tot
        if st.get("ps_ok") is True:
            by_type[tid]["ps_ok_any"] = True

    job_running = store.count_running_jobs_by_container_class(conn)
    return {
        "by_type_id": by_type,
        "job_running_by_container_class": job_running,
    }


def services_status_snapshot(data_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rec in list_service_records(data_dir):
        if str(rec.get("type_id")) != "forge_llm":
            continue
        st = forge_llm_service.status_for_record(rec)
        out.append(
            {
                "id": rec.get("id"),
                "label": rec.get("label"),
                "type_id": rec.get("type_id"),
                "compose_root": rec.get("compose_root"),
                "compose_files": rec.get("compose_files") or [],
                "ps_ok": st.get("ps_ok"),
                "services_running": st.get("services_running"),
                "services_total": st.get("services_total"),
                "last_error": st.get("last_error"),
            }
        )
    return out


def service_ids_for_type_id(data_dir: Path, type_id: str) -> list[str]:
    tid = str(type_id or "").strip()
    out: list[str] = []
    for rec in list_service_records(data_dir):
        if str(rec.get("type_id") or "").strip() == tid:
            sid = str(rec.get("id") or "").strip()
            if sid:
                out.append(sid)
    return sorted(set(out))


