"""Tests for ``fleet_server.self_update`` helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet_server import self_update as su


def test_infer_install_profile_opt_prefix(tmp_path: Path) -> None:
    assert su.infer_install_profile(tmp_path) == "user"
    opt = Path("/opt/forge-fleet")
    assert su.infer_install_profile(opt) == "system"


def test_infer_install_profile_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLEET_SELF_UPDATE_INSTALL_PROFILE", "system")
    assert su.infer_install_profile(tmp_path) == "system"
    monkeypatch.setenv("FLEET_SELF_UPDATE_INSTALL_PROFILE", "user")
    assert su.infer_install_profile(Path("/opt/forge-fleet")) == "user"


def test_build_system_root_install_command_uses_shlex_quote() -> None:
    p = Path("/tmp/test forge/clone")
    cmd = su.build_system_root_install_command(p)
    assert "cd " in cmd
    assert "git pull --ff-only" in cmd
    assert "submodule update" in cmd
    assert "install-update.sh" in cmd
    assert "FLEET_SRC=" in cmd


def test_run_git_self_update_system_returns_paste_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When profile is system, no git pull; returns root paste command."""
    clone = tmp_path / "forge-fleet"
    clone.mkdir(parents=True)
    (clone / ".git").mkdir()
    monkeypatch.setenv("FLEET_GIT_ROOT", str(clone))
    monkeypatch.setenv("FLEET_SELF_UPDATE_INSTALL_PROFILE", "system")
    out = su.run_git_self_update(clone)
    assert out.get("ok") is False
    assert out.get("error") == "system_install_requires_root"
    assert "system_root_install_command" in out
    assert isinstance(out.get("system_root_install_command"), str)
