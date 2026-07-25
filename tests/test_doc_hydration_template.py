"""Doc-hydration docs-check example: template row + job payload stay valid."""

from __future__ import annotations

import json
from pathlib import Path

import fleet_server.container_templates as ct

REPO = Path(__file__).resolve().parent.parent
TEMPLATE_DOC = REPO / "docs" / "examples" / "doc-hydration" / "requirement-template.json"
JOB_PAYLOAD = REPO / "docs" / "examples" / "doc-hydration" / "job-docs-check-request.json"


def test_requirement_template_rows_validate(tmp_path: Path) -> None:
    doc = json.loads(TEMPLATE_DOC.read_text(encoding="utf-8"))
    assert doc["version"] >= 1
    ct.ensure_template_layout(tmp_path)
    for row in doc["templates"]:
        validated = ct.validate_template_row(tmp_path, row)
        assert validated["id"] == "docs_check_worker"
        assert validated["kind"] == "image"


def test_job_payload_shape() -> None:
    payload = json.loads(JOB_PAYLOAD.read_text(encoding="utf-8"))
    assert payload["kind"] == "docker_argv"
    assert isinstance(payload["argv"], list) and payload["argv"]
    meta = payload["meta"]
    assert meta["use_fleet_template_image"] is True
    assert meta["requirements"] == ["docs_check_worker"]
    assert meta["workspace_upload_required"] is True


def test_template_image_injection_into_job_argv() -> None:
    payload = json.loads(JOB_PAYLOAD.read_text(encoding="utf-8"))
    argv = list(payload["argv"])
    out = ct.inject_template_image_into_docker_argv(argv, "fleet-built:abc123")
    assert "fleet-built:abc123" in out
    assert "fleet-template-placeholder:latest" not in out
