"""Report forge-squid shim metrics to forge-llm ``POST /v1/llm/telemetry/events``."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

log = logging.getLogger("forge-squid.gateway_telemetry")

DEFAULT_BASELINE_TOKENS = int(os.environ.get("FORGE_SQUID_TELEMETRY_BASELINE_TOKENS", "8000"))


def telemetry_enabled() -> bool:
    raw = os.environ.get("FORGE_SQUID_GATEWAY_TELEMETRY", "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def gateway_headers(*, run_id: str | None = None, client_model: str | None = None) -> dict[str, str]:
    headers = {"X-Forge-Consumer": "forge-squid", "X-Forge-Consumer-Class": "remote"}
    if run_id:
        headers["X-Forge-Trace-Id"] = run_id[:64]
    if client_model:
        headers["X-Forge-Model"] = client_model[:128]
    return headers


def telemetry_events_url(llm_base_url: str) -> str:
    base = llm_base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/v1/llm/telemetry/events"


def _steps_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    steps = record.get("steps")
    if isinstance(steps, list):
        return [s for s in steps if isinstance(s, dict)]
    return []


def build_shim_metrics(record: dict[str, Any]) -> dict[str, Any]:
    steps = _steps_from_record(record)
    zero_nodes: list[str] = []
    nlp_models: list[str] = []
    llm_calls = int(record.get("llm_calls_made") or record.get("attempts") or 0)
    for step in steps:
        routing = str(step.get("routing") or step.get("routing_class") or "")
        node = str(step.get("id") or step.get("node") or "step")
        if routing == "zero_model":
            zero_nodes.append(node)
        elif routing == "fixed_model":
            llm_calls = max(llm_calls, 1)
    reading = record.get("reading")
    classifiers: dict[str, Any] = {}
    if isinstance(reading, dict):
        decision = reading.get("decision")
        if decision:
            classifiers["dce-01"] = decision
    if record.get("prose_profile"):
        classifiers["prose_profile"] = record["prose_profile"]
    prompt_t = int(record.get("prompt_tokens") or 0)
    completion_t = int(record.get("completion_tokens") or 0)
    avoided = max(len(zero_nodes), 0)
    # Crude baseline: one full-LLM pass minus what was actually spent upstream.
    spent = prompt_t + completion_t
    naive = DEFAULT_BASELINE_TOKENS if spent == 0 else max(spent, DEFAULT_BASELINE_TOKENS)
    saved = max(naive - spent, avoided * 512)
    return {
        "shim_model": record.get("model_alias") or record.get("upstream_model") or "",
        "baseline_model": record.get("backend_model") or record.get("upstream_model") or "",
        "model_calls_avoided": avoided,
        "tokens_saved_estimate": int(saved),
        "llm_calls_made": llm_calls,
        "prompt_tokens": prompt_t,
        "completion_tokens": completion_t,
        "total_ms": int(record.get("elapsed_ms") or 0),
        "deterministic_steps": zero_nodes,
        "nlp_models": nlp_models,
        "classifiers": classifiers,
        "status": record.get("status"),
        "lane": record.get("lane") or record.get("kind"),
    }


def merge_gateway_usage(record: dict[str, Any], answer: dict[str, Any]) -> None:
    usage = answer.get("usage") if isinstance(answer, dict) else None
    if not isinstance(usage, dict):
        return
    tin = int(usage.get("prompt_tokens") or 0)
    tout = int(usage.get("completion_tokens") or 0)
    record["prompt_tokens"] = int(record.get("prompt_tokens") or 0) + tin
    record["completion_tokens"] = int(record.get("completion_tokens") or 0) + tout
    record["llm_calls_made"] = int(record.get("llm_calls_made") or 0) + 1


async def emit_shim_run(
    *,
    llm_base_url: str,
    api_key: str,
    record: dict[str, Any],
    timeout: float = 8.0,
) -> None:
    if not telemetry_enabled() or not llm_base_url.strip():
        return
    url = telemetry_events_url(llm_base_url)
    headers = {"Content-Type": "application/json"}
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    headers.update(gateway_headers(run_id=str(record.get("run_id") or "")))
    body = {
        "kind": "shim_run",
        "source": "squid",
        "trace_id": record.get("run_id"),
        "consumer": "forge-squid",
        "metrics": build_shim_metrics(record),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=headers, json=body)
            r.raise_for_status()
    except httpx.HTTPError as ex:
        log.debug("gateway telemetry post failed: %s", ex)


def schedule_shim_run(
    *,
    llm_base_url: str,
    api_key: str,
    record: dict[str, Any],
) -> None:
    if not telemetry_enabled() or not llm_base_url.strip():
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(emit_shim_run(llm_base_url=llm_base_url, api_key=api_key, record=record))
    except RuntimeError:
        pass
