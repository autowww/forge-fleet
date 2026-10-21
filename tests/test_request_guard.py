"""Request guard unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet_server import request_guard, route_registry, store


def test_anonymous_health_minimal(tmp_path: Path) -> None:
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    dec = request_guard.evaluate(
        db_path=db,
        data_dir=tmp_path,
        method="GET",
        path="/v1/health",
        headers={},
        peer="203.0.113.1:1234",
        body=b"",
        expected_token="secret-token",
        loopback_skips_auth=False,
        listen_host="0.0.0.0",
    )
    assert dec.allow is True
    assert dec.body and dec.body.get("health_mode") == "minimal"


def test_health_full_with_bearer(tmp_path: Path) -> None:
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    tok = "secret-token-value-here-32chars"
    dec = request_guard.evaluate(
        db_path=db,
        data_dir=tmp_path,
        method="GET",
        path="/v1/health",
        headers={"Authorization": f"Bearer {tok}"},
        peer="203.0.113.1:1234",
        body=b"",
        expected_token=tok,
        loopback_skips_auth=False,
        listen_host="0.0.0.0",
    )
    assert dec.allow is True
    assert dec.body and dec.body.get("health_mode") == "full"
    assert dec.auth is not None and dec.auth.ok


def test_route_registry_health_public() -> None:
    spec = route_registry.match_route("/v1/health", "GET")
    assert spec is not None
    assert spec.scope == "public"


def test_unknown_v1_route_404(tmp_path: Path) -> None:
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    dec = request_guard.evaluate(
        db_path=db,
        data_dir=tmp_path,
        method="GET",
        path="/v1/not-a-real-endpoint",
        headers={},
        peer="203.0.113.1:9999",
        body=b"",
        expected_token="",
        loopback_skips_auth=False,
        listen_host="0.0.0.0",
    )
    assert dec.allow is False
    assert dec.http_code == 404


def test_gateway_proxy_does_not_share_read_budget(tmp_path: Path) -> None:
    assert (
        route_registry.route_class_for_path(
            "/v1/app-gateways/market-studio/api/broker/hydration/jobs",
            "GET",
        )
        == "proxy"
    )
    assert route_registry.route_class_for_path("/v1/app-gateways/market-studio", "GET") == "read"
    source = "203.0.113.50"
    now = request_guard.time.time()
    limit = request_guard.LIMITS["read"]
    for _ in range(limit):
        assert request_guard._take_bucket(request_guard._STATE, source, "read", now, limit)
    assert request_guard._take_bucket(request_guard._STATE, source, "read", now, limit) is False
    db = tmp_path / "fleet.sqlite"
    store.connect(db).close()
    proxied = request_guard.evaluate(
        db_path=db,
        data_dir=tmp_path,
        method="GET",
        path="/v1/app-gateways/market-studio/api/broker/hydration/jobs",
        headers={"Authorization": "Bearer secret-token"},
        peer=source + ":9",
        body=b"",
        expected_token="secret-token",
        loopback_skips_auth=False,
        listen_host="0.0.0.0",
    )
    assert proxied.http_code != 429
