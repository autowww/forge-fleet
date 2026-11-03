"""Construct runner adapter from config."""

from __future__ import annotations

import os

from runners.base import RunnerAdapter, RunnerConfig
from runners.llama_cpp import LlamaCppAdapter
from runners.loader import load_runner_config
from runners.ollama import OllamaAdapter
from runners.vllm import VllmAdapter


def _effective_base_url(cfg: RunnerConfig) -> str:
    env = (os.environ.get("OLLAMA_INTERNAL_URL") or "").strip().rstrip("/")
    if env:
        return env
    return cfg.upstream_base_url()


def get_adapter(cfg: RunnerConfig | None = None) -> RunnerAdapter:
    c = cfg or load_runner_config()
    base = _effective_base_url(c)
    if c.kind == "ollama":
        return OllamaAdapter(c, base_url=base)
    if c.kind == "llama_cpp":
        return LlamaCppAdapter(c, base_url=base)
    if c.kind == "vllm":
        return VllmAdapter(c, base_url=base)
    raise ValueError(f"unknown runner kind: {c.kind!r}")
