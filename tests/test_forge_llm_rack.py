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


def test_build_llm_rack_merges_telemetry_summary():
    cp = {
        "queue_depth": 0,
        "active": {"active_model": "composer"},
        "rollup": {"requests": 5, "completion_tokens": 100, "prompt_tokens": 50},
    }
    tel = {
        "window_hours": 24,
        "throughput_requests_per_minute": 0.5,
        "gateway": {"decode_tokens_per_second": 12.3},
        "shim_savings": {
            "squid_shim": {
                "runs": 2,
                "tokens_saved_estimate": 16000,
                "model_calls_avoided": 4,
                "llm_calls_made": 2,
            }
        },
    }
    rack = fls.build_llm_rack(cp, service_id="forge-llm", telemetry=tel)
    assert rack["tokens_saved_estimate"] == 16000
    assert rack["model_calls_avoided"] == 4
    assert rack["shim_runs"] == 2
    assert rack["decode_tokens_per_second"] == 12.3


def test_build_llm_rack_agent_runs_optional():
    cp = {"queue_depth": 0, "active": {}, "rollup": {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}}
    rack_old = fls.build_llm_rack(cp, service_id="forge-llm", telemetry={"gateway": {"requests": 0}})
    assert rack_old.get("agent_runs_24h") is None
    tel = {
        "agent_runs": {
            "runs": 3,
            "non_llm_runs": 1,
            "prompt_tokens_measured": 100,
            "completion_tokens_measured": 40,
            "runs_token_unavailable": 2,
        }
    }
    rack = fls.build_llm_rack(cp, service_id="forge-llm", telemetry=tel)
    assert rack["agent_runs_24h"] == 3
    assert rack["agent_non_llm_runs_24h"] == 1
    assert rack["agent_prompt_tokens_measured_24h"] == 100


def test_tokens_per_sec_tracks_delta():
    service = "test-llm-rate"
    first = fls.tokens_per_sec(service, 1000)
    assert first is None
    time.sleep(0.05)
    second = fls.tokens_per_sec(service, 1050)
    assert second is not None
    assert second > 0
