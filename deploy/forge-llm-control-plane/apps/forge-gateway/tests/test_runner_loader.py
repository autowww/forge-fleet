from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from runners.base import NativeApiUnsupported
from runners.factory import get_adapter
from runners.loader import (
    config_hash,
    load_runner_config,
    render_systemd_dropin,
    reset_runner_cache,
    resolve_runner_path,
)
from runners.llama_cpp import LlamaCppAdapter


def test_resolve_runner_path_granite_file():
    reset_runner_cache()
    p = resolve_runner_path()
    assert p is not None
    assert p.name in ("runner.granite.yaml", "runner.example.yaml", "runner.yaml")


def test_load_granite_task_code_model():
    reset_runner_cache()
    cfg = load_runner_config()
    assert cfg.kind == "ollama"
    assert cfg.bind == "127.0.0.1:11434"
    assert "30b" in cfg.mode_models["task_code"]
    assert cfg.exclusive_slot is False


def test_render_dropin_empty_runtime():
    assert render_systemd_dropin({}) == "[Service]\n"


def test_render_dropin_only_present_keys():
    text = render_systemd_dropin({"OLLAMA_KEEP_ALIVE": "5m"})
    assert "OLLAMA_KEEP_ALIVE" in text
    assert "OLLAMA_HOST" not in text


def test_reject_non_loopback_bind(tmp_path: Path, monkeypatch):
    bad = tmp_path / "runner.yaml"
    bad.write_text("kind: ollama\nbind: 0.0.0.0:11434\nruntime: {}\n", encoding="utf-8")
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(bad))
    reset_runner_cache()
    with pytest.raises(ValueError, match="loopback"):
        load_runner_config(reload=True)


def test_unknown_kind(tmp_path: Path, monkeypatch):
    bad = tmp_path / "runner.yaml"
    bad.write_text("kind: unknown\nbind: 127.0.0.1:11434\n", encoding="utf-8")
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(bad))
    reset_runner_cache()
    with pytest.raises(ValueError, match="unknown runner kind"):
        load_runner_config(reload=True)


def test_config_hash_stable():
    reset_runner_cache()
    h1 = config_hash()
    h2 = config_hash()
    assert h1 == h2
    assert len(h1) == 16


def test_llama_cpp_native_api_unsupported():
    from runners.base import RunnerConfig

    cfg = RunnerConfig(kind="llama_cpp", bind="127.0.0.1:8080")
    adapter = LlamaCppAdapter(cfg, base_url="http://127.0.0.1:8080")

    async def _run():
        with pytest.raises(NativeApiUnsupported):
            await adapter.native_request("POST", "/api/chat", b"{}")

    import asyncio

    asyncio.run(_run())


def test_vllm_adapter_kind():
    reset_runner_cache()
    from runners.base import RunnerConfig

    cfg = RunnerConfig(kind="vllm", bind="127.0.0.1:8000")
    adapter = get_adapter(cfg)
    assert adapter.kind == "vllm"
