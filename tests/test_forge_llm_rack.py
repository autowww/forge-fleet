"""Tests for forge-llm gateway llm_rack enrichment."""

from __future__ import annotations

import time

from fleet_server import forge_llm_service as fls


def test_build_llm_rack_includes_since_fleet_start_fields():
    cp = {
        "queue_depth": 2,
        "active": {"active_model": "qwen2.5:14b", "active_mode": "gpu"},
        "rollup": {
            "requests": 42,
            "prompt_tokens": 1000,
            "completion_tokens": 2000,
            "avg_total_ms": 120.5,
            "swaps": 1,
        },
        "rollup_1h": {
            "requests": 10,
            "avg_total_ms": 90.0,
            "swaps": 0,
        },
    }
    rack = fls.build_llm_rack(cp, service_id="forge-llm", rollup_1h=cp["rollup_1h"])
    assert rack["queue_depth"] == 2
    assert rack["active_model"] == "qwen2.5:14b"
    assert rack["requests_since_fleet_start"] == 42
    assert rack["completion_tokens_since_fleet_start"] == 2000
    assert rack["requests_1h"] == 10


def test_tokens_per_sec_tracks_delta():
    service = "test-llm-rate"
    first = fls.tokens_per_sec(service, 1000)
    assert first is None
    time.sleep(0.05)
    second = fls.tokens_per_sec(service, 1050)
    assert second is not None
    assert second > 0
