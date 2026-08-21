"""Tests for Market Studio rollout scheduler (mock subprocess)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from fleet_server import forge_market_studio_rollout as fmsr


def test_rollout_script_path(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "rollout-forge-market-studio.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    assert fmsr._rollout_script(tmp_path) == script


def test_schedule_rollout_starts_thread(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "rollout-forge-market-studio.sh"
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    with patch("fleet_server.forge_market_studio_rollout.subprocess.run") as mock_run:
        out = fmsr.schedule_rollout(tmp_path)
    assert out["ok"] is True
    assert out.get("scheduled") is True
    assert "rollout-forge-market-studio.sh" in str(out.get("script"))
    mock_run.assert_not_called()


def test_run_rollout_sync_success(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "rollout-forge-market-studio.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    cp = subprocess.CompletedProcess(args=[], returncode=0, stdout="done\n", stderr="")
    with patch("fleet_server.forge_market_studio_rollout.subprocess.run", return_value=cp) as mock_run:
        out = fmsr.run_rollout_sync(tmp_path, timeout_sec=30)
    assert out["ok"] is True
    assert mock_run.call_count == 1
    assert "rollout-forge-market-studio.sh" in mock_run.call_args[0][0][1]


def test_run_rollout_sync_missing_script(tmp_path: Path) -> None:
    try:
        fmsr.run_rollout_sync(tmp_path)
    except FileNotFoundError as ex:
        assert "rollout_script_missing" in str(ex)
    else:
        raise AssertionError("expected FileNotFoundError")
