"""Fleet auto-provisions certificator source-ingest worker requirement template."""

from __future__ import annotations

from pathlib import Path

from fleet_server import certificator_worker_dockerfile as cwd
from fleet_server.container_templates import (
    ensure_template_layout,
    requirement_templates_file,
    template_by_id,
)


def test_ensure_layout_adds_certificator_source_ingest_worker_row(tmp_path: Path) -> None:
    data_dir = tmp_path / "dd"
    data_dir.mkdir()
    ensure_template_layout(data_dir)
    tid = cwd.CERTIFICATOR_SOURCE_INGEST_WORKER_TEMPLATE_ID
    row = template_by_id(data_dir, tid)
    assert row is not None
    assert row.get("kind") == "dockerfile"
    ref = str(row.get("ref") or "")
    assert tid in ref
    p = data_dir / "etc" / "containers" / ref
    assert p.is_file()
    assert "fleet_source_ingest" in p.read_text(encoding="utf-8").lower() or "CMD" in p.read_text(
        encoding="utf-8"
    )


def test_ensure_layout_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "dd2"
    data_dir.mkdir()
    ensure_template_layout(data_dir)
    doc1 = requirement_templates_file(data_dir).read_text(encoding="utf-8")
    ensure_template_layout(data_dir)
    doc2 = requirement_templates_file(data_dir).read_text(encoding="utf-8")
    assert doc1 == doc2
