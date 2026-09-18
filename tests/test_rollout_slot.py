"""Tests for per-service rollout slot acquisition."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fleet_server import infra_flow_submit, rollout_slot, store


def test_acquire_release_cycle(tmp_path: Path, monkeypatch) -> None:
    slots = tmp_path / "slots"
    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", slots)
    out = rollout_slot.try_acquire("market-studio-dev", "job-a", environment="dev")
    assert out["ok"] is True
    conflict = rollout_slot.try_acquire("market-studio-dev", "job-b", environment="dev")
    assert conflict["ok"] is False
    assert conflict["error"] == "rollout_in_progress"
    rollout_slot.release("market-studio-dev", "job-a")
    again = rollout_slot.try_acquire("market-studio-dev", "job-c", environment="dev")
    assert again["ok"] is True


def test_resolve_rollout_target_market_studio() -> None:
    target = rollout_slot.resolve_rollout_target("market-studio-rollout", {"environment": "dev"})
    assert target is not None
    assert target.environment == "dev"
    assert target.service_id == "market-studio-dev"


def test_resolve_rollout_target_normalizes_record_id() -> None:
    target = rollout_slot.resolve_rollout_target(
        "market-studio-rollback",
        {"environment": "forge-market-studio--prod"},
    )
    assert target is not None
    assert target.environment == "prod"
    assert target.service_id == "market-studio"


def test_backup_flow_not_serialized() -> None:
    assert rollout_slot.resolve_rollout_target("market-studio-backup", {"environment": "dev"}) is None


def test_submit_infra_flow_conflict(tmp_path: Path, monkeypatch) -> None:
    slots = tmp_path / "slots"
    db_path = tmp_path / "fleet.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(rollout_slot, "SLOTS_DIR", slots)
    rollout_slot.try_acquire("market-studio-dev", "existing-job", environment="dev", holder_kind="job")

    with patch("fleet_server.infra_flow_submit.runner.spawn"):
        out = infra_flow_submit.submit_infra_flow(
            data_dir,
            db_path,
            {"flow_id": "market-studio-rollout", "inputs": {"environment": "dev"}},
        )
    assert out["ok"] is False
    assert out["error"] == "rollout_in_progress"


def test_find_active_rollout_job(tmp_path: Path) -> None:
    db_path = tmp_path / "fleet.db"
    conn = store.connect(db_path)
    try:
        jid = store.insert_job(
            conn,
            kind="docker_argv",
            argv=["docker", "run"],
            session_id="",
            meta={"rollout_service_id": "market-studio-dev", "infra_flow": True},
        )
        store.update_job(conn, jid, status="running")
        found = store.find_active_rollout_job(conn, "market-studio-dev")
        assert found == jid
        store.update_job(conn, jid, status="completed")
        assert store.find_active_rollout_job(conn, "market-studio-dev") is None
    finally:
        conn.close()
