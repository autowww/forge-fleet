"""Tests for operational Fleet root resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet_server import repo_root as rr


def test_resolve_operational_root_prefers_git_when_apt_tree_lacks_script(
    tmp_path: Path,
    monkeypatch,
) -> None:
    apt_root = tmp_path / "apt"
    apt_root.mkdir()
    (apt_root / "fleet_server").mkdir()
    git_root = tmp_path / "git"
    scripts = git_root / "scripts"
    scripts.mkdir(parents=True)
    roll = scripts / "rollout-forge-market-studio.sh"
    roll.write_text("#!/bin/bash\n", encoding="utf-8")

    monkeypatch.setenv("FLEET_GIT_ROOT", str(git_root))

    root = rr.resolve_operational_root(
        script_relpath=rr.MARKET_STUDIO_ROLLOUT_SCRIPT,
        runtime=apt_root,
    )
    assert root == git_root.resolve()


def test_resolve_operational_root_uses_package_tree_when_present(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    roll = scripts / "rollout-forge-market-studio.sh"
    roll.write_text("#!/bin/bash\n", encoding="utf-8")

    root = rr.resolve_operational_root(
        script_relpath=rr.MARKET_STUDIO_ROLLOUT_SCRIPT,
        runtime=tmp_path,
    )
    assert root == tmp_path.resolve()


def test_resolve_operational_root_missing_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rr, "rollout_root_candidates", lambda runtime=None: [tmp_path])
    with pytest.raises(FileNotFoundError, match="rollout_script_missing"):
        rr.resolve_operational_root(
            script_relpath=rr.MARKET_STUDIO_ROLLOUT_SCRIPT,
            runtime=tmp_path,
        )