"""Dummy-service contract tests for generic rollout API (R8)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from fleet_server import rollout_slot, service_rollout


def test_unknown_service_returns_error() -> None:
    out = service_rollout.schedule_rollout("no-such-service", {})
    assert out["ok"] is False
    assert out["error"] == "unknown_service"


def test_unknown_body_keys_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", tmp_path / "slots")
    out = service_rollout.schedule_rollout("dummy-service", {"not_a_real_key": 1})
    assert out["ok"] is False
    assert out["error"] == "unknown_rollout_keys"


def test_dummy_service_sync_rollout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", tmp_path / "slots")
    script = Path(__file__).resolve().parents[1] / "scripts" / "rollout-dummy-service.sh"
    assert script.is_file()
    with patch("fleet_server.service_rollout.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        out = service_rollout.run_rollout_sync("dummy-service", {"sync": True}, timeout_sec=30)
    assert out.get("ok") is True or out.get("scheduled") is not None or mock_run.call_count == 1
