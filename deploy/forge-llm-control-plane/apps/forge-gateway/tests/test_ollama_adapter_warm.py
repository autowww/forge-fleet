"""Ollama adapter warm/unload must use /api/embed for embedding models."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from runners.loader import load_runner_config, reset_runner_cache
from runners.ollama import OllamaAdapter


def _adapter(tmp_path: Path, monkeypatch, *, exclusive: bool = False) -> OllamaAdapter:
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        f"kind: ollama\nbind: 127.0.0.1:11434\nruntime: {{}}\nexclusive_slot: {str(exclusive).lower()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    reset_runner_cache()
    return OllamaAdapter(load_runner_config(), base_url="http://ollama.test")


def _capture(monkeypatch, calls: list[tuple[str, dict]], status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        calls.append((request.url.path, json.loads(request.content or b"{}")))
        return httpx.Response(status, json={"ok": True})

    real = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr("runners.ollama.httpx.AsyncClient", fake_client)


def test_warm_uses_embed_endpoint_for_embedding_models(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []
    _capture(monkeypatch, calls)
    a = _adapter(tmp_path, monkeypatch)
    ok, err = asyncio.run(a.warm("qwen3-embedding:0.6b"))
    assert ok and err is None
    assert calls[-1][0] == "/api/embed" and calls[-1][1]["model"] == "qwen3-embedding:0.6b"
    ok, _ = asyncio.run(a.warm("nomic-embed-text:latest"))
    assert ok and calls[-1][0] == "/api/embed"
    reset_runner_cache()


def test_warm_uses_generate_for_chat_models(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []
    _capture(monkeypatch, calls)
    a = _adapter(tmp_path, monkeypatch)
    ok, _ = asyncio.run(a.warm("qwen3.5:2b-q4_K_M"))
    assert ok and calls[-1][0] == "/api/generate" and calls[-1][1]["think"] is False
    reset_runner_cache()


def test_unload_embedding_model_uses_embed_keepalive_zero(tmp_path, monkeypatch):
    calls: list[tuple[str, dict]] = []
    _capture(monkeypatch, calls)
    a = _adapter(tmp_path, monkeypatch, exclusive=True)
    asyncio.run(a.unload("qwen3-embedding:0.6b"))
    assert calls[-1][0] == "/api/embed" and calls[-1][1]["keep_alive"] == 0
    reset_runner_cache()
