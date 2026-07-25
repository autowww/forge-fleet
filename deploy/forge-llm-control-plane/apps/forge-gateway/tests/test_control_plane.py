from __future__ import annotations

import json
import os
import tempfile

import pytest

from control_plane.classifier import classify_by_rules
from control_plane.modes import needs_think_false, normalize_mode, model_for_mode
from control_plane.webhooks import sign_payload, verify_signature


def test_normalize_mode():
    assert normalize_mode("task-code") == "task_code"
    assert normalize_mode("interactive") == "interactive"
    assert normalize_mode("bogus") is None


def test_task_code_model():
    assert "30b" in model_for_mode("task_code")


def test_think_false_qwen():
    assert needs_think_false("qwen3:30b-a3b")
    assert not needs_think_false("ctx-unlim-granite41-8b:latest")


def test_classify_rules_coding():
    res = classify_by_rules(
        path="/v1/chat/completions",
        body={"messages": [{"role": "user", "content": "def foo(): pass"}]},
        consumer="test",
    )
    assert res is not None
    assert res.mode == "task_code"


def test_classify_rules_embed():
    res = classify_by_rules(path="/v1/embeddings", body={}, consumer="test")
    assert res is not None
    assert res.mode == "embed"


def test_webhook_hmac():
    body = b'{"ok":true}'
    sig, ts = sign_payload("secret", body, 1000)
    assert verify_signature("secret", body, str(ts), f"sha256={sig}")


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORGE_LLM_DB_PATH", os.path.join(td, "t.sqlite"))
        yield


def test_store_roundtrip(temp_db):
    from control_plane.store import insert_request, list_requests, stats_since
    import time

    rid = insert_request(
        {
            "consumer": "unit",
            "mode": "task_code",
            "served_model": "qwen3:30b-a3b",
            "ok": True,
            "http_status": 200,
        }
    )
    assert rid
    rows = list_requests(time.time() - 60, limit=10)
    assert any(r["id"] == rid for r in rows)
    st = stats_since(time.time() - 60)
    assert st["requests"] >= 1
