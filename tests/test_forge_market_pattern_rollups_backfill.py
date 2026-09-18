"""Tests for pattern cell rollup backfill admin scheduler."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from fleet_server import forge_market_pattern_rollups_backfill as fmprb


def test_backfill_script_path(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "backfill-forge-market-pattern-rollups.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    assert fmprb._backfill_script(tmp_path) == script


def test_schedule_backfill_conflict_when_slot_held(tmp_path: Path, monkeypatch) -> None:
    from fleet_server import rollout_slot

    slots = tmp_path / "slots"
    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", slots)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "backfill-forge-market-pattern-rollups.sh"
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    rollout_slot.try_acquire("market-studio", "busy", environment="prod", holder_kind="legacy")
    out = fmprb.schedule_backfill(tmp_path, overrides={"forge_market_env": "prod"})
    assert out["ok"] is False
    assert out["error"] == "rollout_in_progress"


def test_schedule_backfill_starts_thread(tmp_path: Path, monkeypatch) -> None:
    from fleet_server import rollout_slot

    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", tmp_path / "slots")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "backfill-forge-market-pattern-rollups.sh"
    script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")

    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self) -> None:
            if self._target:
                self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(
        "fleet_server.forge_market_pattern_rollups_backfill.threading.Thread",
        _SyncThread,
    )

    with patch("fleet_server.forge_market_pattern_rollups_backfill.subprocess.run") as mock_run:
        out = fmprb.schedule_backfill(tmp_path, overrides={"tickers": "NVDA", "limit": 5})
    assert out["ok"] is True
    assert out.get("scheduled") is True
    assert "backfill-forge-market-pattern-rollups.sh" in str(out.get("script"))
    assert out.get("overrides", {}).get("FORGE_MARKET_PATTERN_ROLLUPS_TICKERS") == "NVDA"
    assert out.get("overrides", {}).get("FORGE_MARKET_PATTERN_ROLLUPS_LIMIT") == "5"
    mock_run.assert_called_once()


def test_run_backfill_sync_success(tmp_path: Path, monkeypatch) -> None:
    from fleet_server import rollout_slot

    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", tmp_path / "slots")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "backfill-forge-market-pattern-rollups.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    cp = subprocess.CompletedProcess(args=[], returncode=0, stdout="done\n", stderr="")
    with patch("fleet_server.forge_market_pattern_rollups_backfill.subprocess.run", return_value=cp) as mock_run:
        out = fmprb.run_backfill_sync(tmp_path, timeout_sec=30, overrides={"dry_run": True})
    assert out["ok"] is True
    assert mock_run.call_count == 1
    env = mock_run.call_args.kwargs["env"]
    assert env.get("FORGE_MARKET_PATTERN_ROLLUPS_DRY_RUN") == "1"


def test_run_backfill_sync_missing_script(tmp_path: Path) -> None:
    try:
        fmprb.run_backfill_sync(tmp_path)
    except FileNotFoundError as ex:
        assert "backfill_script_missing" in str(ex)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_backfill_shell_script_references_tool() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "backfill-forge-market-pattern-rollups.sh"
    text = script.read_text(encoding="utf-8")
    assert "backfill_pattern_cell_rollups.py" in text
    assert "compose" in text
    assert "run --rm" in text
