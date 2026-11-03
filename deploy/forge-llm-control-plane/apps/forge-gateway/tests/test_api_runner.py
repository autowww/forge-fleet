"""HTTP surface tests (no live Ollama)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        "kind: ollama\nbind: 127.0.0.1:11434\nruntime: {}\nexclusive_slot: false\n"
        "mode_models:\n  task_code: qwen3:30b-a3b\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    monkeypatch.setenv("GATEWAY_AUTH_REQUIRED", "false")
    monkeypatch.setenv("OLLAMA_INTERNAL_URL", "http://127.0.0.1:9")  # unreachable; health only
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    import main as gw_main

    return TestClient(gw_main.app)


def test_llm_runner_endpoint(client: TestClient):
    r = client.get("/v1/llm/runner")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "ollama"
    assert body["bind"] == "127.0.0.1:11434"
    assert "config_hash" in body
    assert "health" in body
    assert "active" in body


def test_native_api_rejects_non_ollama_kind(client: TestClient, tmp_path, monkeypatch):
    cfg = tmp_path / "runner-vllm.yaml"
    cfg.write_text(
        "kind: vllm\nbind: 127.0.0.1:8000\nruntime: {}\nmode_models:\n  interactive: m\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    import importlib
    import main as gw_main

    importlib.reload(gw_main)
    c = TestClient(gw_main.app)
    r = c.post("/api/chat", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 501
