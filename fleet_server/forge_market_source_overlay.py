"""Apply a forge-market source overlay tarball on the Fleet host (private git fallback)."""

from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any


def _default_dest_root() -> Path:
    raw = str(os.environ.get("FORGE_MARKET_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser()
    for candidate in (
        Path("/home/administrator/forge-market"),
        Path.home() / "forge-market",
        Path.home() / "Code" / "forge-market",
    ):
        if candidate.is_dir():
            return candidate
    return Path("/home/administrator/forge-market")


def apply_source_overlay(
    payload: bytes,
    *,
    dest_root: Path | None = None,
) -> dict[str, Any]:
    """Extract gzip tarball overlay onto the forge-market deploy tree."""
    if not payload:
        return {"ok": False, "error": "empty_payload"}
    if len(payload) > 64 * 1024 * 1024:
        return {"ok": False, "error": "payload_too_large", "max_bytes": 64 * 1024 * 1024}

    root = (dest_root or _default_dest_root()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="fm-overlay-") as tmp:
        tmp_path = Path(tmp)
        try:
            with tarfile.open(fileobj=BytesIO(payload), mode="r:gz") as archive:
                archive.extractall(tmp_path, filter="data")
        except tarfile.TarError as exc:
            return {"ok": False, "error": "invalid_tarball", "detail": str(exc)[:400]}

        src = tmp_path
        nested = [p for p in tmp_path.iterdir() if p.is_dir()]
        if len(nested) == 1 and (nested[0] / "studio-server" / "studio_server.py").is_file():
            src = nested[0]

        if not (src / "studio-server" / "studio_server.py").is_file():
            return {
                "ok": False,
                "error": "overlay_layout_invalid",
                "detail": "Expected studio-server/studio_server.py at tarball root",
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

    marker = root / "studio-server" / "studio_server.py"
    return {
        "ok": True,
        "dest_root": str(root),
        "studio_server": str(marker),
        "studio_server_mtime": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(marker.stat().st_mtime),
        ),
        "bytes": len(payload),
    }
