"""Tests for rollout maintenance status reads."""

from __future__ import annotations

import json
from pathlib import Path

from fleet_server import rollout_slot, rollout_status


def test_read_rollout_status_idle(tmp_path: Path, monkeypatch) -> None:
    status_dir = tmp_path / "status"
    monkeypatch.setattr(rollout_status, "STATUS_DIR", status_dir)
    out = rollout_status.read_rollout_status("market-studio")
    assert out["ok"] is True
    assert out["maintenance"] is False
    assert "progress_pct" not in out or out.get("progress_pct") == 0


def test_read_rollout_status_progress_and_job_id(tmp_path: Path, monkeypatch) -> None:
    status_dir = tmp_path / "status"
    slots_dir = tmp_path / "slots"
    monkeypatch.setattr(rollout_status, "STATUS_DIR", status_dir)
    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", slots_dir)
    status_dir.mkdir(parents=True)
    payload = {
        "service_id": "market-studio-dev",
        "maintenance": True,
        "failed": False,
        "current_step": "migrate",
        "current_step_label": "Database migrate",
        "steps_done": ["init", "prepare", "sync", "build"],
    }
    (status_dir / "market-studio-dev.json").write_text(json.dumps(payload), encoding="utf-8")
    rollout_slot.try_acquire(
        "market-studio-dev",
        "job-abc-123",
        environment="dev",
        holder_kind="job",
    )

    out = rollout_status.read_rollout_status("market-studio-dev")
    assert out["maintenance"] is True
    assert out["job_id"] == "job-abc-123"
    assert out["progress_pct"] > 0
    assert out["eta_sec"] > 0
    assert out["current_step_label"] == "Database migrate"


def test_read_rollout_status_preserves_file_job_id(tmp_path: Path, monkeypatch) -> None:
    status_dir = tmp_path / "status"
    monkeypatch.setattr(rollout_status, "STATUS_DIR", status_dir)
    status_dir.mkdir(parents=True)
    payload = {
        "service_id": "market-studio",
        "maintenance": True,
        "job_id": "from-status-file",
        "steps_done": ["init"],
        "current_step": "build",
    }
    (status_dir / "market-studio.json").write_text(json.dumps(payload), encoding="utf-8")

    out = rollout_status.read_rollout_status("market-studio")
    assert out["job_id"] == "from-status-file"
