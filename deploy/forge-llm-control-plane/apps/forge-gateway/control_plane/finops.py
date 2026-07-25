"""Rule-based FinOps suggestions (v1)."""

from __future__ import annotations

import time
from typing import Any

from control_plane.store import list_requests


def suggestions(since_hours: float = 24.0) -> list[dict[str, Any]]:
    since = time.time() - since_hours * 3600
    rows = list_requests(since, limit=500)
    out: list[dict[str, Any]] = []
    if not rows:
        return out

    long_ctx_on_short = sum(
        1
        for r in rows
        if r.get("mode") == "long_ctx"
        and (r.get("prompt_tokens") or 0) < 2000
        and r.get("ok")
    )
    if long_ctx_on_short >= 3:
        out.append(
            {
                "id": "prefer_8b_short",
                "severity": "medium",
                "message": f"{long_ctx_on_short} short prompts used long_ctx; prefer interactive/struct_json.",
            }
        )

    swaps = sum(int(r.get("swap") or 0) for r in rows)
    if swaps >= 5:
        out.append(
            {
                "id": "reduce_swap_thrash",
                "severity": "high",
                "message": f"{swaps} model swaps in window; increase sticky window or batch by mode.",
            }
        )

    task_code_fail = [
        r
        for r in rows
        if r.get("mode") == "task_code" and not r.get("ok")
    ]
    if len(task_code_fail) >= 3:
        out.append(
            {
                "id": "task_code_errors",
                "severity": "high",
                "message": f"{len(task_code_fail)} failed task_code requests; check MoE load and think:false.",
            }
        )

    bounced = sum(1 for r in rows if r.get("http_status") == 503)
    if bounced >= 10:
        out.append(
            {
                "id": "queue_pressure",
                "severity": "medium",
                "message": f"{bounced} bounced (503) requests; consider async webhooks or off-peak batch_eval.",
            }
        )

    return out
