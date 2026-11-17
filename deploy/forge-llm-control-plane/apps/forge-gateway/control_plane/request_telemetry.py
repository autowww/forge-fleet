"""Per-request telemetry enrichment for gateway completions."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from control_plane.classifier import classify_by_rules
from control_plane.context import ForgeContext
from control_plane.store import insert_request


def _prompt_fingerprint(body: dict[str, Any]) -> str:
    msgs = body.get("messages")
    if isinstance(msgs, list):
        text = json.dumps(msgs, sort_keys=True)[:4000]
    else:
        text = json.dumps(body, sort_keys=True)[:4000]
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def classification_snapshot(
    *,
    path: str,
    body: dict[str, Any],
    consumer: str,
    task_id: str,
    deterministic_first: bool,
) -> dict[str, Any]:
    """Rule classifier output stored in llm_requests.meta for analytics."""
    snap: dict[str, Any] = {
        "task_id": task_id,
        "deterministic_first": deterministic_first,
    }
    rule = classify_by_rules(path=path, body=body, consumer=consumer)
    if rule is not None:
        snap["classifier"] = {
            "engine": "rules",
            "mode": rule.mode,
            "model_suggestion": rule.model,
            "source": rule.source,
        }
    else:
        snap["classifier"] = {"engine": "rules", "hit": False}
    return snap


def record_prometheus_completion(
    *,
    path: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    from metrics import load_persisted_state, record_request

    state = load_persisted_state()
    endpoint = "/v1/chat/completions" if "chat" in path else path
    record_request(
        endpoint=endpoint,
        model=model,
        tokens_in=prompt_tokens,
        tokens_out=completion_tokens,
        state=state,
    )


def record_cli_completion(
    *,
    ctx: ForgeContext,
    body: dict[str, Any],
    model: str,
    status: int,
    content: bytes,
    t0: float,
    path: str = "/v1/chat/completions",
    served_model: str | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> None:
    """Persist gateway llm_requests row for CLI lane (token fields left at 0)."""
    meta: dict[str, Any] = {"lane": "cli", "path": path}
    if meta_extra:
        meta.update(meta_extra)
    fc = body.get("forge_cursor")
    if isinstance(fc, dict):
        meta["forge_cursor_mode"] = fc.get("mode")
    insert_request(
        {
            "ts": time.time(),
            "consumer": ctx.consumer,
            "consumer_class": ctx.consumer_class,
            "mode": "chat",
            "requested_model": body.get("model") or model,
            "served_model": served_model or model,
            "total_ms": int((time.perf_counter() - t0) * 1000),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "http_status": status,
            "ok": status < 400,
            "trace_id": ctx.trace_id,
            "prompt_fingerprint": _prompt_fingerprint(body),
            "meta": meta,
        }
    )
    if status < 400:
        try:
            data = json.loads(content)
            usage = data.get("usage") if isinstance(data, dict) else None
            if isinstance(usage, dict):
                tin = int(usage.get("prompt_tokens") or 0)
                tout = int(usage.get("completion_tokens") or 0)
                if tin or tout:
                    record_prometheus_completion(
                        path=path,
                        model=served_model or model,
                        prompt_tokens=tin,
                        completion_tokens=tout,
                    )
        except json.JSONDecodeError:
            pass
