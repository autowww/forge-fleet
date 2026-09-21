"""Tests for generic service source overlay (R10)."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

from fleet_server import service_source_overlay as overlay


def _tar_with_marker(marker: str, content: bytes = b"x") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        info = tarfile.TarInfo(name=marker)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_overlay_layout_invalid(tmp_path: Path) -> None:
    payload = _tar_with_marker("bad.txt")
    out = overlay.apply_source_overlay("dummy-service", payload, dest_root=tmp_path / "dest")
    assert out["ok"] is False
    assert out["error"] == "overlay_layout_invalid"


def test_overlay_applies_marker(tmp_path: Path) -> None:
    payload = _tar_with_marker("marker.txt", b"ok")
    out = overlay.apply_source_overlay("dummy-service", payload, dest_root=tmp_path / "dest")
    assert out["ok"] is True
    assert (tmp_path / "dest" / "marker.txt").read_bytes() == b"ok"
