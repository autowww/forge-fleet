"""Tests for capacity policy persistence."""

from __future__ import annotations

from pathlib import Path

from fleet_server import capacity_policy, space_policy


def test_default_policy_matches_env_for_space(tmp_path: Path):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    assert capacity_policy.space_loop_enabled(data_dir) == space_policy.guardian_enabled()


def test_space_disabled_via_policy_file(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    monkeypatch.setattr(space_policy, "guardian_enabled", lambda: True)
    capacity_policy.save_policy(data_dir, {"space": {"enabled": False}})
    assert capacity_policy.space_loop_enabled(data_dir) is False


def test_memory_apply_stops_default_false(tmp_path: Path):
    data_dir = tmp_path / "fd"
    data_dir.mkdir()
    assert capacity_policy.memory_apply_stops(data_dir) is False
