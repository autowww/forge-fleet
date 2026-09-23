"""Apt/rsync installs ship PACKAGE_VERSION beside fleet_server."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

from fleet_server import versioning


def test_package_semver_reads_package_version_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pkg_root = tmp_path / "pkg"
    (pkg_root / "fleet_server").mkdir(parents=True)
    (pkg_root / "PACKAGE_VERSION").write_text("0.3.114\n", encoding="utf-8")

    fake_versioning = pkg_root / "fleet_server" / "versioning.py"
    fake_versioning.write_text(
        (Path(versioning.__file__).read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    monkeypatch.delenv("FLEET_PACKAGE_SEMVER", raising=False)

    def _no_dist(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(_name)

    monkeypatch.setattr(importlib.metadata, "version", _no_dist)
    monkeypatch.setattr(versioning, "_package_root", lambda: pkg_root)
    assert versioning.package_semver() == "0.3.114"
