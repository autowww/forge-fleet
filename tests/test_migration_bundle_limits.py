"""Tests for per-app migration bundle size limits."""

from __future__ import annotations

import pytest

from fleet_server import migration_bundle_limits as limits


def test_forge_market_builtin_limit_500_gib() -> None:
    row = {"meta": {"app_slug": "forge-market"}, "source_label": "local"}
    assert limits.max_bundle_upload_bytes(row) == 500 * 1024**3


def test_unknown_app_uses_global_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLEET_MIGRATION_BUNDLE_UPLOAD_MAX_BYTES", raising=False)
    monkeypatch.delenv("FLEET_MIGRATION_BUNDLE_MAX_BYTES_BY_APP", raising=False)
    row = {"meta": {"app_slug": "other-app"}, "source_label": "local"}
    assert limits.max_bundle_upload_bytes(row) == 500 * 1024 * 1024


def test_env_json_map_overrides_builtin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FLEET_MIGRATION_BUNDLE_MAX_BYTES_BY_APP",
        '{"forge-market": 999}',
    )
    row = {"meta": {"recipe": "forge-market"}}
    assert limits.max_bundle_upload_bytes(row) == 999


def test_forge_market_uncompressed_builtin_500_gib() -> None:
    row = {"meta": {"app_slug": "forge-market"}, "source_label": "local"}
    assert limits.max_bundle_uncompressed_bytes(row) == 500 * 1024**3


def test_unknown_app_uncompressed_default_2_gib(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLEET_MIGRATION_BUNDLE_MAX_UNCOMPRESSED_BYTES", raising=False)
    row = {"meta": {"app_slug": "other-app"}}
    assert limits.max_bundle_uncompressed_bytes(row) == 2 * 1024 * 1024 * 1024


def test_forge_market_file_cap_above_workspace_default() -> None:
    row = {"meta": {"app_slug": "forge-market"}}
    assert limits.max_bundle_files(row) == 5_000_000
    assert limits.max_bundle_files({"meta": {"app_slug": "other-app"}}) == 200_000


def test_env_per_app_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLEET_MIGRATION_BUNDLE_MAX_BYTES_BY_APP", raising=False)
    monkeypatch.setenv("FLEET_MIGRATION_BUNDLE_MAX_BYTES_FORGE_MARKET", "12345")
    row = {"source_label": "forge-market"}
    assert limits.max_bundle_upload_bytes(row) == 12345
