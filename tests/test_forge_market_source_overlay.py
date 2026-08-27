"""Tests for forge-market source overlay."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

from fleet_server import forge_market_source_overlay as overlay


def _make_archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        data = b'print("studio")\n'
        info = tarfile.TarInfo(name="studio-server/studio_server.py")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_apply_source_overlay(tmp_path: Path):
    payload = _make_archive()
    out = overlay.apply_source_overlay(payload, dest_root=tmp_path / "forge-market")
    assert out["ok"] is True
    assert (tmp_path / "forge-market" / "studio-server" / "studio_server.py").is_file()
