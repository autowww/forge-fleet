"""Tests for ``etc/containers`` + ``etc/services`` layout under the Fleet data dir."""

from __future__ import annotations

import json
from pathlib import Path

from fleet_server import container_layout as cl


def test_ensure_layout_writes_types(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    p = cl.types_file(tmp_path)
    assert p.is_file()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc.get("version") == 1
    ids = {t["id"] for t in doc.get("types", []) if isinstance(t, dict)}
    assert "empty" in ids and "forge_llm" in ids


def test_upsert_and_list_service(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    root = tmp_path / "forge-llm"
    root.mkdir()
    (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    rec = cl.upsert_service(
        tmp_path,
        service_id="lab",
        type_id="forge_llm",
        compose_root=str(root),
        compose_files=[],
        label="Lab",
        allow_replace=False,
    )
    assert rec["id"] == "lab"
    rows = cl.list_service_records(tmp_path)
    assert len(rows) == 1
    assert cl.read_service(tmp_path, "lab") is not None


def test_pick_primary_prefers_default(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    r1 = tmp_path / "a"
    r2 = tmp_path / "b"
    r1.mkdir()
    r2.mkdir()
    (r1 / "compose.yaml").write_text("{}", encoding="utf-8")
    (r2 / "compose.yaml").write_text("{}", encoding="utf-8")
    cl.upsert_service(tmp_path, service_id="zeta", type_id="forge_llm", compose_root=str(r1), compose_files=[], label="z", allow_replace=False)
    cl.upsert_service(tmp_path, service_id="default", type_id="forge_llm", compose_root=str(r2), compose_files=[], label="d", allow_replace=False)
    assert cl.pick_primary_forge_llm_service_id(tmp_path) == "default"


def test_delete_not_found(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    ok, detail = cl.delete_service(tmp_path, "missing")
    assert ok is False
    assert detail == "not_found"
