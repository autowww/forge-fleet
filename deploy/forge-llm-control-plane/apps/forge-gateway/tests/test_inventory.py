"""Catalog inventory endpoint (mocked runner)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    cat_dir = tmp_path / "catalog"
    cat_dir.mkdir()
    cat_file = cat_dir / "mini.json"
    cat_file.write_text(
        '{"vram_tiers_gb":[2,4],"tasks":[{"task_id":"chat","candidates_by_vram_gb":{"4":[{"alias":"Q2","fit":"candidate"}]}}],'
        '"models":[{"alias":"Q2","model_id":"qwen/qwen3-2b","estimated_min_vram_tier_gb":2,"candidate_runtimes":["llama.cpp"]}]}',
        encoding="utf-8",
    )
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        f"kind: ollama\nbind: 127.0.0.1:11434\nruntime: {{}}\nfree_vram_gb: 4\n"
        f"catalog_path: {cat_file}\n"
        "artifact_pins:\n  - runner_model_id: ctx-unlim-qwen3-8b:latest\n    catalog_alias: Q2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    monkeypatch.setenv("GATEWAY_AUTH_REQUIRED", "false")
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    import main as gw_main

    return TestClient(gw_main.app)


def test_llm_catalog_endpoint(client: TestClient):
    with patch("control_plane.inventory.get_adapter") as ga:
        adapter = ga.return_value
        adapter.list_models = AsyncMock(return_value=["ctx-unlim-qwen3-8b:latest", "other:latest"])
        adapter.resident_models = AsyncMock(return_value=["ctx-unlim-qwen3-8b:latest"])
        r = client.get("/v1/llm/catalog")
    assert r.status_code == 200
    body = r.json()
    assert body["schema"] == "forge-llm-catalog-v1"
    assert body["runner"]["free_vram_gb"] == 4
    assert body["runner"]["nominal_vram_tier_gb"] == 4
    assert body["missing_pins"] == []
    assert "ctx-unlim-qwen3-8b:latest" in body["gateway_exposed_model_ids"]
    chat = next(t for t in body["tasks"] if t["task_id"] == "chat")
    assert chat["resolved_pin"] == "ctx-unlim-qwen3-8b:latest"
