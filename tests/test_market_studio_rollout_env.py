"""Tests for market studio rollout env resolution."""

from __future__ import annotations

from pathlib import Path

from fleet_server import env_templates, market_studio_rollout_env


def test_compose_root_prod_dev_clean():
    root = Path(__file__).resolve().parents[1]
    assert market_studio_rollout_env.compose_root_for_env(root, "prod").name == "forge-market-studio"
    assert market_studio_rollout_env.compose_root_for_env(root, "dev").name == "forge-market-studio-dev"
    assert market_studio_rollout_env.compose_root_for_env(root, "clean").name == "market-studio-clean"


def test_clean_ports_distinct_from_dev():
    tpl = env_templates.get_template("forge_market_studio")
    assert tpl is not None
    clean = env_templates.default_ports_for_env(tpl, "clean")
    dev = env_templates.default_ports_for_env(tpl, "dev")
    assert clean["app"] != dev["app"]
    assert clean["postgres"] != dev["postgres"]


def test_known_appdata_volumes_includes_clean():
    vols = market_studio_rollout_env.known_appdata_volumes()
    assert "forge_market_studio_clean_data" in vols
