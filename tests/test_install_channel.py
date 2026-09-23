"""Tests for install_channel detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import install_channel


def test_detect_override_env(monkeypatch) -> None:
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "apt_user")
    assert install_channel.detect_install_channel() == "apt_user"


def test_detect_apt_user_from_dpkg(monkeypatch) -> None:
    monkeypatch.delenv("FLEET_INSTALL_CHANNEL", raising=False)

    def fake_dpkg(pkg: str) -> str | None:
        return "0.3.116" if pkg == "forge-fleet-user" else None

    with patch.object(install_channel, "_dpkg_version", side_effect=fake_dpkg):
        assert install_channel.detect_install_channel() == "apt_user"


def test_install_channel_payload_git_user(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "git_user")
    from unittest.mock import MagicMock

    with patch("subprocess.run", return_value=MagicMock(stdout="", returncode=1)):
        payload = install_channel.install_channel_payload(tmp_path)
    assert payload["ok"] is True
    assert payload["install_channel"] == "git_user"
    assert "migrate-to-apt" in payload["recommended_command"]
