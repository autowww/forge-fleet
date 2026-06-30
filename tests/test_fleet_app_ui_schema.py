"""Validate FAEP JSON schema files parse and list required keys."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMAS = REPO / "docs" / "schemas"


def test_faep_schemas_load() -> None:
    names = [
        "fleet-app-manifest.schema.json",
        "fleet-app-ui-v1.schema.json",
        "fleet-apps-catalog.schema.json",
        "fleet-app-installed.schema.json",
    ]
    for name in names:
        doc = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
        assert doc.get("$id"), name
        assert doc.get("title"), name


def test_ui_schema_includes_v02_widgets() -> None:
    doc = json.loads((SCHEMAS / "fleet-app-ui-v1.schema.json").read_text(encoding="utf-8"))
    kinds = doc["$defs"]["widget"]["properties"]["kind"]["enum"]
    for kind in ("toggle", "status_badge", "event_feed", "link_button"):
        assert kind in kinds
