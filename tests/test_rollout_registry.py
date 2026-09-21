"""Tests for rollout registry loader."""

from __future__ import annotations

from fleet_server import rollout_registry as reg


def test_list_service_ids_includes_market_and_dummy() -> None:
    ids = reg.list_service_ids()
    assert "market-studio" in ids
    assert "dummy-service" in ids


def test_get_market_studio_spec() -> None:
    spec = reg.get("market-studio")
    assert spec is not None
    assert spec.script.endswith("rollout-forge-market-studio.sh")
    assert spec.supports_source_overlay is True
    assert "confirm_dictionary_drops" in spec.overrides


def test_flow_service_id_maps_rollout_flow() -> None:
    assert reg.flow_service_id("market-studio-rollout") == "market-studio"
