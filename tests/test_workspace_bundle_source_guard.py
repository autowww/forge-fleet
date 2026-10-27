"""Git is the only code carrier: job workspace bundles must not smuggle source trees."""

from __future__ import annotations

import os
from unittest import mock

from fleet_server.workspace_bundle import source_bundle_violation


def test_data_bundle_passes():
    names = ["profiles/edge/Default/Preferences", "data/catalog.json", "notes.md", "scripts/run.sh"]
    assert source_bundle_violation(names) is None


def test_git_dir_rejected():
    assert source_bundle_violation(["repo/.git/HEAD", "repo/README.md"]) == "source_bundle_rejected:git_dir"


def test_root_project_manifest_rejected():
    assert source_bundle_violation(["pyproject.toml", "src/a.py"]) == "source_bundle_rejected:project_manifest"
    assert source_bundle_violation(["package.json"]) == "source_bundle_rejected:project_manifest"


def test_many_source_files_rejected_but_few_allowed():
    few = [f"tools/t{i}.py" for i in range(5)]
    assert source_bundle_violation(few) is None
    many = [f"pkg/m{i}.py" for i in range(21)]
    assert source_bundle_violation(many) == "source_bundle_rejected:source_file_limit"


def test_opt_out_env():
    with mock.patch.dict(os.environ, {"FLEET_BUNDLE_ALLOW_SOURCE": "1"}):
        assert source_bundle_violation(["repo/.git/HEAD"]) is None
