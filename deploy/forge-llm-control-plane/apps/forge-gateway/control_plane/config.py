"""Environment configuration for the LLM control plane."""

from __future__ import annotations

import os

OLLAMA_BASE = os.environ.get("OLLAMA_INTERNAL_URL", "http://ollama:11434").rstrip("/")
DB_PATH = os.environ.get("FORGE_LLM_DB_PATH", "/data/forge-llm.sqlite")


def db_path() -> str:
    return os.environ.get("FORGE_LLM_DB_PATH", DB_PATH)


STICKY_WINDOW_SEC = int(os.environ.get("FORGE_LLM_STICKY_WINDOW_SEC", "600"))
MAX_QUEUE_DEPTH = int(os.environ.get("FORGE_LLM_MAX_QUEUE_DEPTH", "64"))
DEFAULT_HOLD_TIMEOUT_SEC = int(os.environ.get("FORGE_LLM_HOLD_TIMEOUT_SEC", "300"))


def _quarantined_models() -> frozenset[str]:
    env = os.environ.get("FORGE_LLM_QUARANTINED_MODELS", "").strip()
    if env:
        return frozenset(m.strip() for m in env.split(",") if m.strip())
    try:
        from runners.loader import load_runner_config

        return load_runner_config().quarantined_models
    except (ImportError, OSError, ValueError):
        return frozenset(
            {
                "ctx-unlim-qwen25-coder-7b:latest",
                "qwen2.5-coder:7b",
            }
        )


def classifier_model() -> str:
    override = os.environ.get("FORGE_LLM_CLASSIFIER_MODEL", "").strip()
    if override:
        return override
    try:
        from runners.loader import load_runner_config

        return load_runner_config().classifier_model
    except (ImportError, OSError, ValueError):
        return "ibm/granite4:tiny-h"


QUARANTINED_MODELS = _quarantined_models()
CLASSIFIER_MODEL = classifier_model()
