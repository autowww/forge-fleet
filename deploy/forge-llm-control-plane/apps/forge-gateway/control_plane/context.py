"""Per-request Forge control-plane context from headers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from control_plane.modes import ModeId, normalize_mode


WaitPolicy = Literal["hold", "bounce"]
ConsumerClass = Literal["local", "remote"]


@dataclass
class ForgeContext:
    consumer: str
    consumer_class: ConsumerClass
    mode: ModeId | None
    wait: WaitPolicy | None
    async_job: bool
    webhook_url: str | None
    webhook_secret: str | None
    trace_id: str | None

    @classmethod
    def from_headers(cls, headers: dict[str, str], body_mode: str | None = None) -> ForgeContext:
        h = {k.lower(): v for k, v in headers.items()}
        consumer = (h.get("x-forge-consumer") or "anonymous").strip()[:128]
        cc_raw = (h.get("x-forge-consumer-class") or "remote").strip().lower()
        consumer_class: ConsumerClass = "local" if cc_raw == "local" else "remote"
        mode = normalize_mode(h.get("x-forge-llm-mode") or body_mode)
        wait_raw = (h.get("x-forge-wait") or "").strip().lower()
        wait: WaitPolicy | None = None
        if wait_raw in ("hold", "bounce"):
            wait = wait_raw  # type: ignore[assignment]
        async_job = (h.get("x-forge-async") or "").strip() in ("1", "true", "yes")
        return cls(
            consumer=consumer,
            consumer_class=consumer_class,
            mode=mode,
            wait=wait,
            async_job=async_job,
            webhook_url=(h.get("x-forge-webhook-url") or "").strip() or None,
            webhook_secret=(h.get("x-forge-webhook-secret") or "").strip() or None,
            trace_id=(h.get("x-forge-trace-id") or "").strip()[:64] or None,
        )
