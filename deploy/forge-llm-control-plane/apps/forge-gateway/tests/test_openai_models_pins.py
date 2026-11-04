"""GET /v1/models advertises all artifact pins for Open WebUI."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        """
kind: ollama
bind: 127.0.0.1:11434
runtime: {}
artifact_pins:
  - runner_model_id: ctx-unlim-qwen3-8b:latest
    enabled: true
  - runner_model_id: qwen3:30b-a3b
    enabled: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    monkeypatch.setenv("GATEWAY_AUTH_REQUIRED", "false")
    monkeypatch.setenv("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", "true")

    async def fake_adapter(method, path, body, *, timeout=600.0):
        assert method == "GET" and path == "/v1/models"
        payload = {"object": "list", "data": [{"id": "qwen3.5:2b", "object": "model"}]}
        return 200, json.dumps(payload).encode(), {"content-type": "application/json"}

    monkeypatch.setattr("control_plane.router.adapter_openai", fake_adapter)
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    import main as gw_main

    return TestClient(gw_main.app)


def test_models_lists_all_pins_not_only_ollama_tags(client: TestClient):
    r = client.get("/v1/models")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()["data"]}
    assert "ctx-unlim-qwen3-8b:latest" in ids
    assert "qwen3:30b-a3b" in ids
    assert "qwen3.5:2b" not in ids
