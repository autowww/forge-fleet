"""Rollups for token / throughput / squid shim savings analytics."""

from __future__ import annotations

import json
from typing import Any

from control_plane.store import list_requests, list_telemetry_events, stats_since
from control_plane.telemetry_schema import METRIC_CATALOG, shim_savings_row


def _parse_meta(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("meta_json")
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def stats_enriched(since_ts: float) -> dict[str, Any]:
    base = stats_since(since_ts)
    rows = list_requests(since_ts, limit=5000)
    by_consumer: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_lane: dict[str, dict[str, Any]] = {}
    infer_ms_sum = 0
    infer_ms_n = 0
    completion_sum = 0

    for row in rows:
        if not row.get("ok"):
            continue
        consumer = str(row.get("consumer") or "anonymous")
        model = str(row.get("served_model") or "_unknown")
        meta = _parse_meta(row)
        lane = str(meta.get("lane") or "unknown")
        tin = int(row.get("prompt_tokens") or 0)
        tout = int(row.get("completion_tokens") or 0)
        total_ms = int(row.get("total_ms") or 0)
        infer_ms = int(row.get("infer_ms") or 0)
        if infer_ms > 0:
            infer_ms_sum += infer_ms
            infer_ms_n += 1
            completion_sum += tout

        for bucket, key in ((by_consumer, consumer), (by_model, model), (by_lane, lane)):
            if key not in bucket:
                bucket[key] = {
                    "requests": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_ms_sum": 0,
                }
            bucket[key]["requests"] += 1
            bucket[key]["prompt_tokens"] += tin
            bucket[key]["completion_tokens"] += tout
            bucket[key]["total_ms_sum"] += total_ms

    decode_tps = None
    if infer_ms_sum > 0:
        decode_tps = round(completion_sum / (infer_ms_sum / 1000.0), 2)

    return {
        **base,
        "decode_tokens_per_second": decode_tps,
        "by_consumer": by_consumer,
        "by_served_model": by_model,
        "by_lane": by_lane,
    }


def shim_savings_since(since_ts: float) -> dict[str, Any]:
    events = list_telemetry_events(since_ts, kind="shim_run", limit=5000)
    totals = {
        "runs": 0,
        "model_calls_avoided": 0,
        "tokens_saved_estimate": 0,
        "llm_calls_made": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_ms": 0,
    }
    by_shim: dict[str, dict[str, int]] = {}
    classifier_labels: dict[str, int] = {}
    nlp_models: dict[str, int] = {}

    for ev in events:
        try:
            payload = json.loads(ev.get("payload_json") or "{}")
        except json.JSONDecodeError:
            continue
        metrics = shim_savings_row(payload.get("metrics") or {})
        totals["runs"] += 1
        totals["model_calls_avoided"] += metrics["model_calls_avoided"]
        totals["tokens_saved_estimate"] += metrics["tokens_saved_estimate"]
        totals["llm_calls_made"] += metrics["llm_calls_made"]
        totals["prompt_tokens"] += metrics["prompt_tokens"]
        totals["completion_tokens"] += metrics["completion_tokens"]
        totals["total_ms"] += metrics["total_ms"]
        shim = metrics["shim_model"] or "unknown"
        if shim not in by_shim:
            by_shim[shim] = {
                "runs": 0,
                "tokens_saved_estimate": 0,
                "model_calls_avoided": 0,
            }
        by_shim[shim]["runs"] += 1
        by_shim[shim]["tokens_saved_estimate"] += metrics["tokens_saved_estimate"]
        by_shim[shim]["model_calls_avoided"] += metrics["model_calls_avoided"]
        for step in metrics["deterministic_steps"]:
            label = str(step)
            classifier_labels[label] = classifier_labels.get(label, 0) + 1
        for name in metrics["nlp_models"]:
            nlp_models[str(name)] = nlp_models.get(str(name), 0) + 1
        for name, count in metrics["classifiers"].items():
            try:
                n = int(count)
            except (TypeError, ValueError):
                n = 1
            classifier_labels[str(name)] = classifier_labels.get(str(name), 0) + n

    gateway_saved = 0
    gateway_rows = list_requests(since_ts, limit=5000)
    for row in gateway_rows:
        meta = _parse_meta(row)
        if meta.get("deterministic_first"):
            gateway_saved += int(meta.get("tokens_saved_estimate") or 0)

    return {
        "squid_shim": totals,
        "by_shim_model": by_shim,
        "classifier_outputs": classifier_labels,
        "nlp_models": nlp_models,
        "gateway_tokens_saved_estimate": gateway_saved,
    }


def telemetry_summary(since_ts: float, window_hours: float) -> dict[str, Any]:
    enriched = stats_enriched(since_ts)
    shim = shim_savings_since(since_ts)
    span = max(window_hours * 3600.0, 1.0)
    rpm = round((enriched.get("requests") or 0) * 3600.0 / span, 2)
    return {
        "schema_version": "forge.llm.telemetry.v1",
        "window_hours": window_hours,
        "metric_catalog": METRIC_CATALOG,
        "throughput_requests_per_minute": rpm,
        "gateway": enriched,
        "shim_savings": shim,
    }
