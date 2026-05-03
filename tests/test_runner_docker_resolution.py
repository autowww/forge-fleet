"""Docker/podman CLI resolution for docker_argv jobs."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet_server import runner


def test_docker_executable_respects_absolute_override(tmp_path: Path) -> None:
    fake = tmp_path / "mydocker"
    fake.write_text("#!/bin/sh\necho hi\n")
    fake.chmod(0o755)
    with patch.dict(os.environ, {"FLEET_DOCKER_BIN": str(fake)}, clear=False):
        assert runner._docker_executable() == str(fake.resolve())


def test_docker_executable_resolves_bare_name_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FLEET_DOCKER_BIN=docker must resolve via PATH, not be passed literally to Popen."""
    monkeypatch.setenv("FLEET_DOCKER_BIN", "docker")
    monkeypatch.delenv("FLEET_NO_PODMAN_FALLBACK", raising=False)
    resolved = runner._docker_executable()
    assert resolved != "docker"
    assert Path(resolved).name in ("docker", "docker.io")


@patch("fleet_server.runner.shutil.which")
@patch("fleet_server.runner._first_existing_executable")
def test_override_docker_name_uses_which(
    mock_candidates: pytest.MonkeyPatch,
    mock_which: pytest.MonkeyPatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_candidates.return_value = None
    mock_which.side_effect = lambda name, path=None: (
        "/usr/bin/docker" if name == "docker" else "/usr/bin/podman" if name == "podman" else None
    )
    monkeypatch.delenv("FLEET_NO_PODMAN_FALLBACK", raising=False)
    monkeypatch.setenv("FLEET_DOCKER_BIN", "docker")
    assert runner._docker_executable() == "/usr/bin/docker"


@patch("fleet_server.runner.shutil.which")
@patch("fleet_server.runner._first_existing_executable")
def test_falls_back_to_podman_when_docker_missing(
    mock_candidates: pytest.MonkeyPatch,
    mock_which: pytest.MonkeyPatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_candidates.return_value = None

    def _which(name: str, path: str | None = None) -> str | None:
        if name == "docker":
            return None
        if name == "podman":
            return "/usr/bin/podman"
        return None

    mock_which.side_effect = _which
    monkeypatch.delenv("FLEET_DOCKER_BIN", raising=False)
    monkeypatch.delenv("FLEET_NO_PODMAN_FALLBACK", raising=False)
    assert runner._docker_executable() == "/usr/bin/podman"


@patch("fleet_server.runner.shutil.which")
@patch("fleet_server.runner._first_existing_executable")
def test_no_podman_when_opt_out(
    mock_candidates: pytest.MonkeyPatch,
    mock_which: pytest.MonkeyPatch,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_candidates.return_value = None
    mock_which.return_value = None
    monkeypatch.delenv("FLEET_DOCKER_BIN", raising=False)
    monkeypatch.setenv("FLEET_NO_PODMAN_FALLBACK", "1")
    assert runner._docker_executable() == "docker"
