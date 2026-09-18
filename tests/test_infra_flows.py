"""Tests for infra flow catalog and workspace packaging."""

from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path

from fleet_server import infra_flows


def test_list_infra_flows_includes_rollout():
    ids = {f["id"] for f in infra_flows.list_infra_flows()}
    assert "market-studio-rollout" in ids
    assert "market-studio-audit" in ids


def test_load_and_package_flow():
    doc = infra_flows.load_infra_flow("market-studio-backup")
    assert doc["id"] == "market-studio-backup"
    blob = infra_flows.build_workspace_tar_gz(doc, {"environment": "prod", "label": "test"})
    with tarfile.open(fileobj=BytesIO(blob), mode="r:gz") as tf:
        names = tf.getnames()
    assert "flow.lmeta" in names
    assert "inputs.json" in names
    assert ".forge_workspace_manifest.json" in names
