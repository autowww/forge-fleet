"""Prometheus metrics for forge-gateway (Ollama proxy)."""

from __future__ import annotations

import os
from typing import Any

from prometheus_client import Counter, Histogram

REQUESTS_TOTAL = Counter(
    "forge_ollama_requests_total",
    "Total proxied Ollama API requests",
    ["endpoint"],
)

TOKENS_IN_TOTAL = Counter(
    "forge_ollama_tokens_in_total",
    "Total prompt tokens evaluated (best-effort from Ollama responses)",
    ["model"],
)

TOKENS_OUT_TOTAL = Counter(
    "forge_ollama_tokens_out_total",
    "Total completion tokens evaluated (best-effort from Ollama responses)",
    ["model"],
)

REQUEST_LATENCY = Histogram(
    "forge_ollama_request_duration_seconds",
    "Latency of Ollama proxied requests",
    ["endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 15, 30, 60, 120, 300),
)

STATE_PATH = os.environ.get("GATEWAY_STATE_PATH", "/data/state.json")


def _default_state() -> dict[str, Any]:
    return {
        "requests_total": 0,
        "tokens_in_total": 0,
        "tokens_out_total": 0,
        "per_model": {},
    }


def load_persisted_state() -> dict[str, Any]:
    import json

    if not os.path.exists(STATE_PATH):
        return _default_state()
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_state()
        return data
    except OSError:
        return _default_state()


def save_persisted_state(state: dict[str, Any]) -> None:
    import json
    import tempfile

    parent = os.path.dirname(STATE_PATH) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix="state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_PATH)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def restore_counters_from_disk() -> None:
    """Restore Prometheus counters from persisted JSON (container restarts)."""
    st = load_persisted_state()
    rt = int(st.get("requests_total", 0) or 0)
    if rt > 0:
        REQUESTS_TOTAL.labels(endpoint="/api").inc(rt)

    pm = st.get("per_model") or {}
    if not isinstance(pm, dict):
        return
    for m, v in pm.items():
        if not isinstance(v, dict):
            continue
        try:
            tin = int(v.get("in", 0) or 0)
            tout = int(v.get("out", 0) or 0)
        except ValueError:
            continue
        if tin:
            TOKENS_IN_TOTAL.labels(model=str(m)).inc(tin)
        if tout:
            TOKENS_OUT_TOTAL.labels(model=str(m)).inc(tout)


def record_request(
    *,
    endpoint: str,
    model: str | None,
    tokens_in: int | None,
    tokens_out: int | None,
    state: dict[str, Any],
) -> None:
    """Update counters, Prometheus metrics, and persisted JSON snapshot."""
    m = model or "_unknown"
    tin = int(tokens_in or 0)
    tout = int(tokens_out or 0)

    REQUESTS_TOTAL.labels(endpoint=endpoint).inc()
    if tin:
        TOKENS_IN_TOTAL.labels(model=m).inc(tin)
    if tout:
        TOKENS_OUT_TOTAL.labels(model=m).inc(tout)

    state["requests_total"] = int(state.get("requests_total", 0)) + 1
    state["tokens_in_total"] = int(state.get("tokens_in_total", 0)) + tin
    state["tokens_out_total"] = int(state.get("tokens_out_total", 0)) + tout
    pm = state.setdefault("per_model", {})
    if m not in pm:
        pm[m] = {"in": 0, "out": 0}
    pm[m]["in"] = int(pm[m].get("in", 0)) + tin
    pm[m]["out"] = int(pm[m].get("out", 0)) + tout
    save_persisted_state(state)
