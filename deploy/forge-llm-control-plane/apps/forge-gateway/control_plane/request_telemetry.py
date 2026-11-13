"""Per-request telemetry enrichment for gateway completions."""

from __future__ import annotations

from typing import Any

from control_plane.classifier import classify_by_rules


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
