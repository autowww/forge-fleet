"""Tests for apt upgrade signal queue."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fleet_server import package_upgrade


def test_write_upgrade_signal_apt_user(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "apt_user")
    with patch.object(package_upgrade, "timer_active", return_value=True):
        out = package_upgrade.write_upgrade_signal(tmp_path, mode="upgrade", lifecycle_ok=True)
    assert out["ok"] is True
    assert out["status"] == "queued"
    sig = tmp_path / "upgrade-request.json"
    assert sig.is_file()
    doc = json.loads(sig.read_text(encoding="utf-8"))
    assert doc["lifecycle_ok"] is True
    assert doc["package"] == "forge-fleet-user"


def test_write_upgrade_signal_rejects_git(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "git_user")
    out = package_upgrade.write_upgrade_signal(tmp_path, mode="upgrade", lifecycle_ok=True)
    assert out["ok"] is False
    assert out["error"] == "not_apt_channel"


def test_queue_status_complete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FLEET_INSTALL_CHANNEL", "apt_user")
    (tmp_path / "upgrade-result.json").write_text(
        json.dumps({"ok": True, "completed_at": "2026-01-01T00:00:00Z"}) + "\n",
        encoding="utf-8",
    )
    status = package_upgrade.queue_status(tmp_path)
    assert status["phase"] == "complete"
