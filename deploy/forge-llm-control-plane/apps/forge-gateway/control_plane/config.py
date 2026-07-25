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
CLASSIFIER_MODEL = os.environ.get(
    "FORGE_LLM_CLASSIFIER_MODEL", "ibm/granite4:tiny-h"
).strip()
QUARANTINED_MODELS = frozenset(
    m.strip()
    for m in os.environ.get(
        "FORGE_LLM_QUARANTINED_MODELS",
        "ctx-unlim-qwen25-coder-7b:latest,qwen2.5-coder:7b",
    ).split(",")
    if m.strip()
)
