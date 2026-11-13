from __future__ import annotations

import json
import os
import tempfile
import time

import pytest


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORGE_LLM_DB_PATH", os.path.join(td, "t.sqlite"))
        yield


def test_telemetry_event_ingest_and_shim_rollup(temp_db):
    from control_plane.store import insert_request, insert_telemetry_event
    from control_plane.telemetry_analytics import shim_savings_since, stats_enriched

    since = time.time() - 120
    insert_request(
        {
            "consumer": "forge-squid",
            "mode": "interactive",
            "requested_model": "composer",
            "served_model": "cursor-cli",
            "ok": True,
            "http_status": 200,
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_ms": 5000,
            "infer_ms": 4500,
            "meta": {"lane": "cli", "classifier": {"engine": "rules", "hit": False}},
        }
    )
    insert_telemetry_event(
        {
            "source": "squid",
            "kind": "shim_run",
            "consumer": "forge-squid",
            "payload": {
                "metrics": {
                    "shim_model": "forge-squid-composer",
                    "model_calls_avoided": 3,
                    "tokens_saved_estimate": 12000,
                    "llm_calls_made": 1,
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "deterministic_steps": ["dce_classify", "graph_parse"],
                    "nlp_models": ["request_ir"],
                    "classifiers": {"intent": 1},
                }
            },
        }
    )
    enriched = stats_enriched(since)
    assert enriched["requests"] >= 1
    assert enriched["by_consumer"].get("forge-squid", {}).get("prompt_tokens") == 100
    assert enriched["decode_tokens_per_second"] is not None

    shim = shim_savings_since(since)
    assert shim["squid_shim"]["runs"] == 1
    assert shim["squid_shim"]["tokens_saved_estimate"] == 12000
    assert shim["squid_shim"]["model_calls_avoided"] == 3
    assert "dce_classify" in shim["classifier_outputs"]
    assert shim["nlp_models"].get("request_ir") == 1


def test_validate_and_batch_events(temp_db):
    from control_plane.telemetry_schema import validate_event
    from control_plane.store import list_telemetry_events
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    assert validate_event({"kind": "shim_run", "source": "squid", "metrics": {}})[0]
    bad = validate_event({"kind": "nope", "source": "squid"})[0]
    assert not bad

    body = {
        "events": [
            {
                "kind": "classifier",
                "source": "squid",
                "metrics": {"name": "dce-01", "label": "chat"},
            },
            {
                "kind": "nlp",
                "source": "squid",
                "metrics": {"model": "request_ir", "tokens_in": 10},
            },
        ]
    }
    r = client.post("/v1/llm/telemetry/events", json=body)
    assert r.status_code == 200
    assert len(r.json().get("ids", [])) == 2
    rows = list_telemetry_events(time.time() - 60, limit=10)
    kinds = {row["kind"] for row in rows}
    assert "classifier" in kinds
    assert "nlp" in kinds
