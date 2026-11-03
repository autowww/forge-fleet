"""Model runner adapters (Ollama, llama.cpp, vLLM)."""

from __future__ import annotations

from runners.base import NativeApiUnsupported, RunnerAdapter, RunnerConfig
from runners.loader import (
    config_hash,
    load_runner_config,
    render_systemd_dropin,
    reset_runner_cache,
)

__all__ = [
    "NativeApiUnsupported",
    "RunnerAdapter",
    "RunnerConfig",
    "config_hash",
    "get_adapter",
    "load_runner_config",
    "render_systemd_dropin",
    "reset_runner_cache",
]


def __getattr__(name: str):
    if name == "get_adapter":
        from runners.factory import get_adapter as _get_adapter

        return _get_adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
