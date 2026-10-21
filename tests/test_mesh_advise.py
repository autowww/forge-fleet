"""Mesh offload advise (local-only path)."""

from __future__ import annotations

from pathlib import Path

from fleet_server import mesh_advise, store


def test_advise_local_only(tmp_path: Path) -> None:
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    out = mesh_advise.advise(tmp_path, db, service_id="demo", cpu_seconds=10.0, transfer_mb=0.0)
    assert out.get("ok") is True
    assert out.get("best") is not None
    assert isinstance(out.get("ranked"), list)
