"""Generic service source overlay from gzip tarball."""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from fleet_server import rollout_registry


def apply_source_overlay(
    service_id: str,
    payload: bytes,
    *,
    dest_root: Path | None = None,
) -> dict[str, Any]:
    spec = rollout_registry.get(service_id)
    if spec is None:
        return {"ok": False, "error": "unknown_service", "service_id": service_id}
    if not spec.supports_source_overlay:
        return {"ok": False, "error": "overlay_not_supported", "service_id": service_id}
    if not payload:
        return {"ok": False, "error": "empty_payload"}
    if len(payload) > 64 * 1024 * 1024:
        return {"ok": False, "error": "payload_too_large", "max_bytes": 64 * 1024 * 1024}

    overlay = spec.source_overlay or {}
    marker = str(overlay.get("layout_marker") or "").strip()
    if not marker:
        return {"ok": False, "error": "layout_marker_missing"}
    root = (dest_root or Path(str(overlay.get("dest_root") or ""))).expanduser().resolve()
    if not str(overlay.get("dest_root") or dest_root):
        return {"ok": False, "error": "dest_root_missing"}
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="svc-overlay-") as tmp:
        tmp_path = Path(tmp)
        try:
            with tarfile.open(fileobj=BytesIO(payload), mode="r:gz") as archive:
                archive.extractall(tmp_path, filter="data")
        except tarfile.TarError as exc:
            return {"ok": False, "error": "invalid_tarball", "detail": str(exc)[:400]}

        src = tmp_path
        nested = [p for p in tmp_path.iterdir() if p.is_dir()]
        if len(nested) == 1 and (nested[0] / marker).is_file():
            src = nested[0]

        if not (src / marker).is_file():
            return {
                "ok": False,
                "error": "overlay_layout_invalid",
                "detail": f"Expected {marker} at tarball root",
            }

        rsync = subprocess.run(
            [
                "rsync",
                "-a",
                "--exclude",
                ".git/",
                "--exclude",
                "/data/",
                "--exclude",
                ".venv/",
                f"{src}/",
                f"{root}/",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if rsync.returncode != 0:
            return {
                "ok": False,
                "error": "rsync_failed",
                "returncode": rsync.returncode,
                "stderr": (rsync.stderr or "")[-2000:],
            }
        marker_path = root / marker

    return {
        "ok": True,
        "service_id": service_id,
        "dest_root": str(root),
        "layout_marker": marker,
        "marker_path": str(marker_path),
        "marker_mtime": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(marker_path.stat().st_mtime),
        ),
        "bytes": len(payload),
    }

