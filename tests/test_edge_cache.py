"""Tests for Cloudflare edge cache policy and headers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet_server import app_gateway, edge_cache, operator_ui_settings


def test_resolve_ttl_disabled(tmp_path: Path) -> None:
    operator_ui_settings.put_settings(tmp_path, {"edge": {"cache": {"enabled": False, "routes": [{"method": "GET", "path": "/v1/admin/snapshot", "ttl_s": 10}]}}})
    ttl = edge_cache.resolve_ttl(method="GET", path="/v1/admin/snapshot", status=200, data_dir=tmp_path)
    assert ttl == 0


def test_resolve_ttl_enabled_route(tmp_path: Path) -> None:
    operator_ui_settings.put_settings(
        tmp_path,
        {"edge": {"cache": {"enabled": True, "max_ttl_s": 300, "routes": [{"method": "GET", "path": "/v1/admin/snapshot", "ttl_s": 10}]}}},
    )
    ttl = edge_cache.resolve_ttl(method="GET", path="/v1/admin/snapshot?jobs_limit=5", status=200, data_dir=tmp_path)
    assert ttl == 10


def test_health_hard_bypass(tmp_path: Path) -> None:
    operator_ui_settings.put_settings(
        tmp_path,
        {"edge": {"cache": {"enabled": True, "routes": [{"method": "GET", "path": "/v1/health", "ttl_s": 60}]}}},
    )
    assert edge_cache.resolve_ttl(method="GET", path="/v1/health", status=200, data_dir=tmp_path) == 0


def test_ruleset_targets_app_gateways_only() -> None:
    body = edge_cache._ruleset_body("granite.forgedc.net", enabled=True)
    rules = body["rules"]
    assert len(rules) == 1
    expr = rules[0]["expression"]
    assert "starts_with(http.request.uri.path, \"/v1/app-gateways/\")" in expr
    assert "custom_key" not in json.dumps(rules[0])
    assert rules[0]["action_parameters"]["edge_ttl"]["mode"] == "respect_origin"


def test_clamp_ttl(tmp_path: Path) -> None:
    operator_ui_settings.put_settings(tmp_path, {"edge": {"cache": {"enabled": True, "max_ttl_s": 15}}})
    policy = edge_cache.cache_policy(tmp_path)
    assert edge_cache.clamp_ttl(99999, policy) == 15


def test_apply_headers(tmp_path: Path) -> None:
    headers: dict[str, str] = {}
    edge_cache.apply_response_cache_headers(headers, 10, "/v1/admin/snapshot")
    assert headers["Cache-Control"] == "private, no-store"
    assert headers["Cloudflare-CDN-Cache-Control"] == "public, max-age=10"
    assert "Authorization" in headers.get("Vary", "")


def test_gateway_per_path_route_ttl(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    app_gateway.save_gateway(
        data_dir,
        {"service_id": "market-studio", "upstream": "http://127.0.0.1:9000"},
    )
    operator_ui_settings.put_settings(data_dir, {"edge": {"cache": {"enabled": True, "max_ttl_s": 60}}})
    with patch.object(edge_cache, "maybe_sync_cloudflare", return_value={"ok": False, "error": "not_orchestrator"}):
        edge_cache.register_gateway_edge_cache(
            data_dir,
            "market-studio",
            {
                "routes": [
                    {"path": "api/pipeline/coverage/market-bars", "ttl_s": 15},
                    {"path": "api/prices/bars-compact", "ttl_s": 5},
                ],
            },
        )
    rec = app_gateway.load_gateway(data_dir, "market-studio")
    assert rec is not None
    ttl_cov = edge_cache.resolve_gateway_proxy_ttl(
        method="GET",
        rest_path="api/pipeline/coverage/market-bars",
        status=200,
        gateway_record=rec,
        data_dir=data_dir,
    )
    ttl_bars = edge_cache.resolve_gateway_proxy_ttl(
        method="GET",
        rest_path="api/prices/bars-compact",
        status=200,
        gateway_record=rec,
        data_dir=data_dir,
    )
    ttl_other = edge_cache.resolve_gateway_proxy_ttl(
        method="GET",
        rest_path="api/other",
        status=200,
        gateway_record=rec,
        data_dir=data_dir,
    )
    assert ttl_cov == 15
    assert ttl_bars == 5
    assert ttl_other == 0
    ttl_cell = edge_cache.resolve_gateway_proxy_ttl(
        method="GET",
        rest_path="api/pipeline/coverage/market-bars/cell",
        status=200,
        gateway_record=rec,
        data_dir=data_dir,
    )
    assert ttl_cell == 15


def test_register_gateway_and_proxy_ttl(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    app_gateway.save_gateway(
        data_dir,
        {"service_id": "market-studio", "upstream": "http://127.0.0.1:9000"},
    )
    operator_ui_settings.put_settings(data_dir, {"edge": {"cache": {"enabled": True, "max_ttl_s": 60}}})
    with patch.object(edge_cache, "maybe_sync_cloudflare", return_value={"ok": False, "error": "not_orchestrator"}):
        out = edge_cache.register_gateway_edge_cache(data_dir, "market-studio", {"ttl_s": 30, "paths": ["api/foo"]})
    assert out["ok"] is True
    assert out["edge_cache"]["ttl_s"] == 30
    rec = app_gateway.load_gateway(data_dir, "market-studio")
    assert rec is not None
    ttl = edge_cache.resolve_gateway_proxy_ttl(
        method="GET",
        rest_path="api/foo",
        status=200,
        gateway_record=rec,
        data_dir=data_dir,
    )
    assert ttl == 30


def test_register_rejects_bad_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "fleet"
    app_gateway.save_gateway(data_dir, {"service_id": "app1", "upstream": "http://127.0.0.1:9000"})
    operator_ui_settings.put_settings(data_dir, {"edge": {"cache": {"enabled": True}}})
    out = edge_cache.register_gateway_edge_cache(
        data_dir,
        "app1",
        {"ttl_s": 10, "paths": ["../escape"]},
    )
    assert out["ok"] is False
    assert out.get("error") == "invalid_path"


def test_sync_not_orchestrator(tmp_path: Path) -> None:
    operator_ui_settings.put_settings(tmp_path, {"edge": {"cache": {"orchestrate": False}}})
    sync = edge_cache.sync_zone_cache_rules(tmp_path)
    assert sync["ok"] is False
    assert sync["error"] == "not_orchestrator"


def test_sync_calls_cloudflare_when_orchestrator(tmp_path: Path) -> None:
    operator_ui_settings.put_settings(
        tmp_path,
        {
            "edge": {
                "public_hostname": "granite.example",
                "cache": {
                    "orchestrate": True,
                    "enabled": True,
                    "zone_id": "zone123",
                },
            },
        },
    )
    edge_cache.save_token(tmp_path, "tok-test")
    calls: list[str] = []

    def fake_upsert(zone_id: str, token: str, ruleset: dict) -> None:
        calls.append(zone_id)
        assert token == "tok-test"
        assert ruleset.get("rules")

    with patch.object(edge_cache, "_upsert_zone_ruleset", side_effect=fake_upsert):
        sync = edge_cache.sync_zone_cache_rules(tmp_path)
    assert sync["ok"] is True
    assert calls == ["zone123"]


def test_get_settings_redacts_token(tmp_path: Path) -> None:
    edge_cache.save_token(tmp_path, "secret-token-value")
    loaded = operator_ui_settings.get_settings(tmp_path)
    cache = loaded["settings"]["edge"]["cache"]
    assert cache.get("token_configured") is True
    blob = json.dumps(loaded)
    assert "secret-token-value" not in blob
