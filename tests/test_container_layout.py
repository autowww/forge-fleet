"""Tests for ``etc/containers`` + ``etc/services`` layout under the Fleet data dir."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fleet_server import container_layout as cl


def test_ensure_layout_writes_types(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    p = cl.types_file(tmp_path)
    assert p.is_file()
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert int(doc.get("version") or 0) >= 2
    assert isinstance(doc.get("categories"), list) and doc["categories"]
    ids = {t["id"] for t in doc.get("types", []) if isinstance(t, dict)}
    assert "empty" in ids and "forge_llm" in ids
    for t in doc.get("types", []):
        if isinstance(t, dict) and t.get("id") == "forge_llm":
            assert t.get("category_id") == "service"


def test_materialize_forge_llm_inherits_service_capabilities(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    doc = cl.load_types(tmp_path)
    mat = cl.materialize_types(doc)
    row = next(x for x in mat if isinstance(x, dict) and x.get("id") == "forge_llm")
    ec = row["effective_capabilities"]
    assert ec["api_manage_services"] is True
    assert ec["admin_spawnable"] is True
    assert ec["allow_docker_argv_jobs"] is False


def test_v1_types_json_migrates_on_load(tmp_path: Path) -> None:
    etc_containers = tmp_path / "etc" / "containers"
    etc_containers.mkdir(parents=True)
    v1 = {
        "version": 1,
        "types": [
            {"id": "empty", "container_class": "empty"},
            {"id": "host_cpu_probe", "container_class": "host_cpu_probe"},
            {"id": "forge_llm", "container_class": "forge_llm"},
        ],
    }
    cl.types_file(tmp_path).write_text(json.dumps(v1), encoding="utf-8")
    doc = cl.load_types(tmp_path)
    assert int(doc.get("version") or 0) >= 2
    assert isinstance(doc.get("categories"), list)
    by_id = {str(t.get("id")): t for t in doc.get("types", []) if isinstance(t, dict)}
    assert by_id["empty"].get("category_id") == "system"
    assert by_id["host_cpu_probe"].get("category_id") == "job"
    assert by_id["forge_llm"].get("category_id") == "service"


def test_upsert_service_rejects_job_type(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    root = tmp_path / "x"
    root.mkdir()
    (root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="type_not_api_manageable"):
        cl.upsert_service(
            tmp_path,
            service_id="bad",
            type_id="host_cpu_probe",
            compose_root=str(root),
            compose_files=[],
            label="x",
            allow_replace=False,
        )


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


def test_allocate_forge_llm_service_id_prefers_default_then_lab_then_llm_n(tmp_path: Path) -> None:
    cl.ensure_layout(tmp_path)
    assert cl.allocate_forge_llm_service_id(tmp_path) == "default"
    cl.services_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    (cl.service_file(tmp_path, "default")).write_text('{"id":"default","version":1}\n', encoding="utf-8")
    assert cl.allocate_forge_llm_service_id(tmp_path) == "lab"
    (cl.service_file(tmp_path, "lab")).write_text('{"id":"lab","version":1}\n', encoding="utf-8")
    assert cl.allocate_forge_llm_service_id(tmp_path) == "llm2"
    (cl.service_file(tmp_path, "llm2")).write_text('{"id":"llm2","version":1}\n', encoding="utf-8")
    assert cl.allocate_forge_llm_service_id(tmp_path) == "llm3"
