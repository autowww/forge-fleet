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
    _categories_by_id,
    _write_json_atomic,
    ensure_layout,
    load_types,
    types_file,
)
from fleet_server.container_layout.services import list_service_records, service_ids_for_type_id

_SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

_TYPE_ID_RE = _SERVICE_ID_RE

_CONTAINER_CLASS_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")

_CAPABILITY_KEYS = ("admin_spawnable", "api_manage_services", "allow_docker_argv_jobs")

# Types that must never be removed via API (system contracts).
RESERVED_TYPE_IDS: frozenset[str] = frozenset({"empty"})


def validate_type_id(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not _TYPE_ID_RE.match(s):
        raise ValueError("invalid_type_id")
    return s


def validate_container_class(raw: str) -> str:
    s = str(raw or "").strip().lower()
    if not s:
        raise ValueError("container_class_required")
    if not _CONTAINER_CLASS_RE.match(s):
        raise ValueError("invalid_container_class")
    return s


def _validate_category_row(cat: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cat, dict):
        raise ValueError("category_must_be_object")
    cid = str(cat.get("id") or "").strip()
    if not cid:
        raise ValueError("category_id_required")
    title = str(cat.get("title") or cid).strip()[:200]
    desc = str(cat.get("description") or "")[:4000]
    caps_in = cat.get("capabilities") if isinstance(cat.get("capabilities"), dict) else {}
    caps: dict[str, bool] = {}
    for k in _CAPABILITY_KEYS:
        if k in caps_in:
            caps[k] = bool(caps_in[k])
    return {"id": cid, "title": title, "description": desc, "capabilities": caps}


def _validate_requirements_for_type(data_dir: Path, raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("requirements_must_be_list")
    out: list[str] = []
    for x in raw:
        rid = container_templates.validate_requirement_id(str(x))
        if container_templates.template_by_id(data_dir, rid) is None:
            raise ValueError(f"unknown_requirement:{rid}")
        out.append(rid)
    # de-dupe preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for r in out:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return uniq


def validate_type_row(
    data_dir: Path,
    row: dict[str, Any],
    *,
    categories_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ValueError("type_must_be_object")
    tid = validate_type_id(str(row.get("id") or ""))
    cid = str(row.get("category_id") or "").strip()
    if not cid or cid not in categories_by_id:
        raise ValueError("unknown_category_id")
    cclass = validate_container_class(str(row.get("container_class") or ""))
    title = str(row.get("title") or "").strip()[:200]
    if not title:
        raise ValueError("type_title_required")
    notes = str(row.get("notes") or "")[:8000]
    reqs = _validate_requirements_for_type(data_dir, row.get("requirements"))
    out: dict[str, Any] = {
        "id": tid,
        "category_id": cid,
        "container_class": cclass,
        "title": title,
        "notes": notes,
    }
    if reqs:
        out["requirements"] = reqs
    for k in _CAPABILITY_KEYS:
        if k in row:
            out[k] = bool(row[k])
    return out


def validate_types_document(data_dir: Path, doc: dict[str, Any]) -> dict[str, Any]:
    ensure_layout(data_dir)
    if not isinstance(doc, dict):
        raise ValueError("document_must_be_object")
    try:
        ver = int(doc.get("version") or 2)
    except (TypeError, ValueError):
        raise ValueError("invalid_version")
    if ver < 1:
        raise ValueError("invalid_version")
    cats_raw = doc.get("categories")
    if not isinstance(cats_raw, list) or len(cats_raw) == 0:
        raise ValueError("categories_required")
    categories: list[dict[str, Any]] = []
    cat_ids: set[str] = set()
    for c in cats_raw:
        cc = _validate_category_row(c if isinstance(c, dict) else {})
        if cc["id"] in cat_ids:
            raise ValueError("duplicate_category_id")
        cat_ids.add(cc["id"])
        categories.append(cc)
    categories_by_id = {c["id"]: c for c in categories}

    types_raw = doc.get("types")
    if not isinstance(types_raw, list):
        raise ValueError("types_must_be_list")
    types_clean: list[dict[str, Any]] = []
    type_ids: set[str] = set()
    for row in types_raw:
        tr = validate_type_row(data_dir, row if isinstance(row, dict) else {}, categories_by_id=categories_by_id)
        if tr["id"] in type_ids:
            raise ValueError("duplicate_type_id")
        type_ids.add(tr["id"])
        types_clean.append(tr)

    return {"version": ver, "categories": categories, "types": types_clean}


def save_types_document(data_dir: Path, doc: dict[str, Any]) -> dict[str, Any]:
    clean = validate_types_document(data_dir, doc)
    _write_json_atomic(types_file(data_dir), clean)
    return clean


def add_type_row(data_dir: Path, row: dict[str, Any]) -> dict[str, Any]:
    doc = load_types(data_dir)
    cats = _categories_by_id(doc)
    tid = validate_type_id(str(row.get("id") or ""))
    for t in doc.get("types", []):
        if isinstance(t, dict) and str(t.get("id") or "") == tid:
            raise ValueError("type_id_exists")
    new_row = validate_type_row(data_dir, row, categories_by_id=cats)
    types_list = [t for t in doc.get("types", []) if isinstance(t, dict)]
    types_list.append(new_row)
    doc["types"] = types_list
    try:
        v = int(doc.get("version") or 2)
    except (TypeError, ValueError):
        v = 2
    doc["version"] = max(v, 2)
    save_types_document(data_dir, doc)
    return new_row


def update_type_row(data_dir: Path, type_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    doc = load_types(data_dir)
    tid_req = validate_type_id(type_id)
    cats = _categories_by_id(doc)
    types_list: list[dict[str, Any]] = []
    found: dict[str, Any] | None = None
    for t in doc.get("types", []):
        if not isinstance(t, dict):
            continue
        if str(t.get("id") or "") == tid_req:
            found = copy.deepcopy(t)
        else:
            types_list.append(copy.deepcopy(t))
    if found is None:
        raise FileNotFoundError("not_found")
    merged = {**found, **patch, "id": tid_req}
    new_row = validate_type_row(data_dir, merged, categories_by_id=cats)
    types_list.append(new_row)
    doc["types"] = types_list
    save_types_document(data_dir, doc)
    return new_row


def delete_type_row(data_dir: Path, type_id: str, conn: sqlite3.Connection) -> tuple[bool, str]:
    tid = validate_type_id(type_id)
    if tid in RESERVED_TYPE_IDS:
        return False, "reserved_type_id"
    doc = load_types(data_dir)
    types_list = [t for t in doc.get("types", []) if isinstance(t, dict)]
    victim: dict[str, Any] | None = None
    kept: list[dict[str, Any]] = []
    for t in types_list:
        if str(t.get("id") or "") == tid:
            victim = t
        else:
            kept.append(t)
    if victim is None:
        return False, "not_found"
    cc = str(victim.get("container_class") or "").strip().lower()
    if cc:
        running = store.count_running_jobs_by_container_class(conn)
        n = int(running.get(cc, 0))
        if n > 0:
            return False, "running_jobs_for_container_class"
    svcs = service_ids_for_type_id(data_dir, tid)
    if svcs:
        return False, "services_referencing_type"
    doc["types"] = kept
    save_types_document(data_dir, doc)
    return True, "removed"


def pick_primary_forge_llm_service_id(data_dir: Path) -> str | None:
    """Prefer ``default``, else lexicographically first ``forge_llm`` service."""
    ids: list[str] = []
    for rec in list_service_records(data_dir):
        if str(rec.get("type_id")) == "forge_llm":
            ids.append(str(rec.get("id") or ""))
    ids = [i for i in ids if i]
    if not ids:
        return None
    if "default" in ids:
        return "default"
    return sorted(ids)[0]
