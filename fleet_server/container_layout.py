"""On-disk container **types** and **service** definitions under ``$FLEET_DATA_DIR/etc/``.

Layout (created at startup, same ``--data-dir`` as ``fleet.sqlite`` — matches
``install-user.sh`` / ``install-update.sh`` state directories):

- ``etc/containers/types.json`` — catalog: which classes exist and what Fleet admin/API may do.
- ``etc/services/<id>.json`` — one **managed** stack per file (today: ``forge_llm`` compose roots).

If ``FLEET_FORGE_LLM_ROOT`` is set and ``etc/services/`` is empty, a ``default.json``
service is written once so existing env-based installs keep working.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from fleet_server import forge_llm_service

_SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")

DEFAULT_TYPES: dict[str, Any] = {
    "version": 1,
    "types": [
        {
            "id": "empty",
            "container_class": "empty",
            "title": "Empty (smoke)",
            "admin_spawnable": False,
            "api_manage_services": False,
            "notes": "Hierarchy anchor / unit tests only — not offered in Fleet admin or managed-service APIs.",
        },
        {
            "id": "host_cpu_probe",
            "container_class": "host_cpu_probe",
            "title": "Host CPU probe",
            "admin_spawnable": False,
            "api_manage_services": False,
            "notes": "Short-lived probe jobs via POST /v1/admin/test-fleet (not a persisted compose service).",
        },
        {
            "id": "forge_llm",
            "container_class": "forge_llm",
            "title": "Forge LLM (Compose)",
            "admin_spawnable": True,
            "api_manage_services": True,
            "notes": "Docker Compose stack; add instances under etc/services/*.json or POST /v1/container-services.",
        },
    ],
}


def fleet_data_dir_from_server(server: object) -> Path:
    return Path(str(getattr(server, "fleet_data_dir", "") or ".")).resolve()


def etc_root(data_dir: Path) -> Path:
    return (data_dir / "etc").resolve()


def types_file(data_dir: Path) -> Path:
    return etc_root(data_dir) / "containers" / "types.json"


def services_dir(data_dir: Path) -> Path:
    return etc_root(data_dir) / "services"


def service_file(data_dir: Path, service_id: str) -> Path:
    return services_dir(data_dir) / f"{service_id}.json"


def layout_paths_payload(data_dir: Path) -> dict[str, Any]:
    return {
        "fleet_data_dir": str(data_dir.resolve()),
        "types_file": str(types_file(data_dir)),
        "services_dir": str(services_dir(data_dir)),
    }


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(raw, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_layout(data_dir: Path) -> None:
    data_dir = data_dir.resolve()
    tpath = types_file(data_dir)
    if not tpath.is_file():
        _write_json_atomic(tpath, DEFAULT_TYPES)
    services_dir(data_dir).mkdir(parents=True, exist_ok=True)
    _migrate_env_llm_service(data_dir)


def _migrate_env_llm_service(data_dir: Path) -> None:
    root_raw = str(os.environ.get("FLEET_FORGE_LLM_ROOT") or "").strip()
    if not root_raw:
        return
    sdir = services_dir(data_dir)
    if any(sdir.glob("*.json")):
        return
    root = Path(root_raw).expanduser().resolve()
    if not root.is_dir() or not (root / "compose.yaml").is_file():
        return
    extras: list[str] = []
    raw = str(os.environ.get("FLEET_FORGE_LLM_COMPOSE_FILES") or "").strip()
    if raw:
        for part in raw.split(","):
            n = Path(part.strip()).name
            if n and n != "compose.yaml" and (root / n).is_file():
                if n not in extras:
                    extras.append(n)
    rec: dict[str, Any] = {
        "version": 1,
        "id": "default",
        "type_id": "forge_llm",
        "label": "default (from FLEET_FORGE_LLM_ROOT)",
        "compose_root": str(root),
        "compose_files": extras,
    }
    _write_json_atomic(service_file(data_dir, "default"), rec)


def load_types(data_dir: Path) -> dict[str, Any]:
    ensure_layout(data_dir)
    p = types_file(data_dir)
    try:
        raw = p.read_text(encoding="utf-8")
        o = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_TYPES)
    return o if isinstance(o, dict) else dict(DEFAULT_TYPES)


def type_by_id(data_dir: Path, type_id: str) -> dict[str, Any] | None:
    doc = load_types(data_dir)
    for t in doc.get("types", []):
        if isinstance(t, dict) and str(t.get("id") or "") == type_id:
            return t
    return None


def validate_service_id(service_id: str) -> str:
    sid = str(service_id or "").strip().lower()
    if not _SERVICE_ID_RE.match(sid):
        raise ValueError("invalid_service_id")
    return sid


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
    tmeta = type_by_id(data_dir, type_id)
    if tmeta is None:
        raise ValueError("unknown_type_id")
    if not bool(tmeta.get("api_manage_services")):
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
