"""Telemetry event kinds and field contracts (forge-llm analytics)."""

from __future__ import annotations

from typing import Any, Literal

SCHEMA_VERSION = "forge.llm.telemetry.v1"

EventKind = Literal[
    "gateway_completion",
    "shim_run",
    "classifier",
    "nlp",
]

EventSource = Literal["gateway", "squid", "client"]

# Metrics catalog (analytics dimensions)
METRIC_CATALOG: dict[str, str] = {
    "throughput_rpm": "Completed requests per minute in the window",
    "prompt_tokens": "Sum of prompt / input tokens (OpenAI usage)",
    "completion_tokens": "Sum of completion / output tokens",
    "total_tokens": "prompt_tokens + completion_tokens",
    "avg_total_ms": "Mean end-to-end latency (queue + inference)",
    "avg_infer_ms": "Mean inference-only latency",
    "decode_tps": "completion_tokens / (infer_ms/1000) when infer_ms > 0",
    "model_calls_avoided": "Squid shim: LLM calls not made (deterministic / zero_model)",
    "tokens_saved_estimate": "Squid shim: estimated tokens vs naive full-LLM baseline",
    "classifier_hits": "Count of rule or NLP classifier decisions recorded",
    "nlp_invocations": "Count of on-gateway or reported NLP model calls",
}


def validate_event(payload: dict[str, Any]) -> tuple[bool, str]:
    """Light validation for POST /v1/llm/telemetry/events."""
    kind = payload.get("kind")
    source = payload.get("source")
    if kind not in ("gateway_completion", "shim_run", "classifier", "nlp"):
        return False, f"invalid kind: {kind!r}"
    if source not in ("gateway", "squid", "client"):
        return False, f"invalid source: {source!r}"
    metrics = payload.get("metrics")
    if metrics is not None and not isinstance(metrics, dict):
        return False, "metrics must be an object"
    return True, "ok"


def shim_savings_row(metrics: dict[str, Any]) -> dict[str, Any]:
    """Normalize squid shim_run metrics for rollups."""
    return {
        "model_calls_avoided": int(metrics.get("model_calls_avoided") or 0),
        "tokens_saved_estimate": int(metrics.get("tokens_saved_estimate") or 0),
        "llm_calls_made": int(metrics.get("llm_calls_made") or 0),
        "prompt_tokens": int(metrics.get("prompt_tokens") or 0),
        "completion_tokens": int(metrics.get("completion_tokens") or 0),
        "total_ms": int(metrics.get("total_ms") or 0),
        "shim_model": str(metrics.get("shim_model") or metrics.get("requested_model") or ""),
        "baseline_model": str(metrics.get("baseline_model") or ""),
        "deterministic_steps": list(metrics.get("deterministic_steps") or []),
        "nlp_models": list(metrics.get("nlp_models") or []),
        "classifiers": dict(metrics.get("classifiers") or {}),
    }
