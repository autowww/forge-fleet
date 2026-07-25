"""MECE LLM usage modes and Granite model mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModeId = Literal[
    "interactive",
    "task_code",
    "struct_json",
    "reason_short",
    "long_ctx",
    "codegen_loop",
    "embed",
    "batch_eval",
]

ALL_MODES: tuple[ModeId, ...] = (
    "interactive",
    "task_code",
    "struct_json",
    "reason_short",
    "long_ctx",
    "codegen_loop",
    "embed",
    "batch_eval",
)

DEFAULT_WAIT_BY_MODE: dict[ModeId, Literal["hold", "bounce"]] = {
    "interactive": "bounce",
    "struct_json": "bounce",
    "reason_short": "bounce",
    "task_code": "hold",
    "long_ctx": "hold",
    "codegen_loop": "hold",
    "embed": "bounce",
    "batch_eval": "hold",
}

MODE_MODEL: dict[ModeId, str] = {
    "interactive": "ctx-unlim-qwen3-8b:latest",
    "task_code": "qwen3:30b-a3b",
    "struct_json": "ctx-unlim-qwen3-8b:latest",
    "reason_short": "qwen3:30b-a3b",
    "long_ctx": "ctx-unlim-qwen3-14b:latest",
    "codegen_loop": "ctx-unlim-granite41-8b:latest",
    "embed": "nomic-embed-text:latest",
    "batch_eval": "ctx-unlim-qwen3-14b:latest",
}

THINK_FALSE_PREFIXES = ("qwen3", "qwen2.5", "deepseek-r1")


@dataclass(frozen=True)
class ModeResolution:
    mode: ModeId
    model: str
    source: str  # header | body | classify_rules | classify_llm | default


def normalize_mode(raw: str | None) -> ModeId | None:
    if not raw:
        return None
    m = raw.strip().lower().replace("-", "_")
    if m in ALL_MODES:
        return m  # type: ignore[return-value]
    return None


def model_for_mode(mode: ModeId, requested_model: str | None = None) -> str:
    if mode == "batch_eval" and requested_model:
        return requested_model
    return MODE_MODEL[mode]


def needs_think_false(model: str) -> bool:
    base = model.split(":")[0].lower()
    return any(base.startswith(p) or p in model.lower() for p in THINK_FALSE_PREFIXES)
