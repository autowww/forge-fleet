"""Market Studio rollout contract endpoint."""

from pathlib import Path

from fleet_server import forge_market_studio_rollout as fmsr


def test_rollout_contract_payload():
    out = fmsr.rollout_contract_payload()
    assert out["ok"] is True
    assert out["contract"] == fmsr.ROLLOUT_CONTRACT
    assert "backend_label_guard" in out["features"]


def test_rollout_script_requests_backend_version_guard():
    script = Path(__file__).resolve().parents[1] / "scripts" / "rollout-forge-market-studio.sh"
    text = script.read_text(encoding="utf-8")
    assert "_REQUESTED_BACKEND_VERSION" in text
    assert "release_label_mismatch" in text
    assert "migrator_stale" in text
