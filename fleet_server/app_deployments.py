"""Read live app deployment status from managed compose services."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from fleet_server import container_layout, managed_compose_service as mcs

_IMAGE_TAG_RE = re.compile(r"^([^@:]+)(?::([^@]+))?(?:@(.+))?$")


def _image_identity(image_ref: str) -> dict[str, str]:
    ref = str(image_ref or "").strip()
    if not ref:
        return {"image": "", "tag": "", "digest": ""}
    m = _IMAGE_TAG_RE.match(ref)
    if not m:
        return {"image": ref, "tag": "", "digest": ""}
    repo, tag, digest = m.group(1) or "", m.group(2) or "", m.group(3) or ""
    if ref.startswith("sha256:"):
        return {"image": ref, "tag": "", "digest": ref}
    if digest:
        return {"image": repo, "tag": tag, "digest": digest}
    return {"image": repo, "tag": tag, "digest": ""}


def _inspect_container_image(container_id: str) -> dict[str, str]:
    cid = str(container_id or "").strip()
    if not cid:
        return {}
    try:
        r = subprocess.run(
            ["docker", "inspect", "--format", "{{json .}}", cid],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if r.returncode != 0:
        return {}
    try:
        doc = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(doc, dict):
        return {}
    config = doc.get("Config") if isinstance(doc.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    image = str(doc.get("Image") or config.get("Image") or "")
    repo_digests = doc.get("RepoDigests") if isinstance(doc.get("RepoDigests"), list) else []
    digest = ""
    if repo_digests:
        digest = str(repo_digests[0] or "")
        if "@" in digest:
            digest = digest.split("@", 1)[1]
    ident = _image_identity(image)
    if digest:
        ident["digest"] = digest
    schema_head = str(labels.get("forge.schema_head") or labels.get("schema_head") or "")
    if schema_head:
        ident["schema_head"] = schema_head
    return ident


def _primary_app_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Service") or row.get("Name") or "").lower()
        if "market-app" in name or "market_app" in name or name.endswith("-app"):
            return row
    return rows[0] if rows else None


def get_app_deployment(data_dir: Path, service_id: str) -> dict[str, Any]:
    rec = container_layout.read_service(data_dir, service_id)
    if rec is None:
        return {"ok": False, "error": "not_found", "service_id": service_id}
    try:
        health = mcs.status_for_record(rec)
    except (ValueError, FileNotFoundError, OSError) as ex:
        return {"ok": False, "error": "status_failed", "detail": str(ex)[:400], "service_id": service_id}
    root = Path(str(rec.get("compose_root") or "")).expanduser()
    raw_cf = rec.get("compose_files")
    extras = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else []
    rel = mcs.resolve_compose_files(root, extras)
    rows, ps_err = mcs.compose_ps(root, rel)
    app_row = _primary_app_row(rows)
    image_ref = str((app_row or {}).get("Image") or "")
    ident = _image_identity(image_ref)
    container_id = str((app_row or {}).get("ID") or (app_row or {}).get("Id") or "")
    if container_id:
        ident.update({k: v for k, v in _inspect_container_image(container_id).items() if v})
    compose_project = str(rec.get("compose_project") or rec.get("id") or service_id)
    return {
        "ok": True,
        "service_id": service_id,
        "compose_project": compose_project,
        "compose_root": str(root),
        "image": ident.get("image") or image_ref,
        "tag": ident.get("tag") or "",
        "digest": ident.get("digest") or "",
        "schema_head": ident.get("schema_head") or "",
        "health": health,
        "ps_ok": ps_err is None,
        "ps_error": ps_err,
    }
