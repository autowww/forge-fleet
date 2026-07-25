"""Request queue with bounce (503) and hold semantics."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from control_plane.config import MAX_QUEUE_DEPTH


@dataclass
class QueueTicket:
    ticket_id: str
    enqueued_at: float = field(default_factory=time.time)
    event: asyncio.Event = field(default_factory=asyncio.Event)
    position: int = 0


class InferenceQueue:
    def __init__(self) -> None:
        self._waiting: deque[QueueTicket] = deque()
        self._lock = asyncio.Lock()
        self._active = 0
        self._max_concurrent = 1

    async def depth(self) -> int:
        async with self._lock:
            return len(self._waiting) + self._active

    async def acquire(self, ticket_id: str, *, hold: bool, timeout_sec: float) -> dict[str, Any]:
        ticket = QueueTicket(ticket_id=ticket_id)
        async with self._lock:
            if len(self._waiting) >= MAX_QUEUE_DEPTH:
                return {
                    "ok": False,
                    "reason": "queue_full",
                    "queue_position": len(self._waiting),
                    "retry_after_sec": 30,
                }
            if self._active < self._max_concurrent:
                self._active += 1
                return {"ok": True, "queue_wait_ms": 0}
            ticket.position = len(self._waiting) + 1
            self._waiting.append(ticket)
        if not hold:
            return {
                "ok": False,
                "reason": "busy",
                "queue_position": ticket.position,
                "retry_after_sec": min(60, max(5, ticket.position * 10)),
            }
        try:
            await asyncio.wait_for(ticket.event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            async with self._lock:
                try:
                    self._waiting.remove(ticket)
                except ValueError:
                    pass
            return {
                "ok": False,
                "reason": "queue_timeout",
                "queue_position": ticket.position,
                "retry_after_sec": 15,
            }
        wait_ms = int((time.time() - ticket.enqueued_at) * 1000)
        return {"ok": True, "queue_wait_ms": wait_ms}

    async def release(self) -> None:
        async with self._lock:
            if self._waiting:
                nxt = self._waiting.popleft()
                nxt.event.set()
            else:
                self._active = max(0, self._active - 1)


inference_queue = InferenceQueue()
