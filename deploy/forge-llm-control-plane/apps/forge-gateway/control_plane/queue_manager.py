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

    def _reap_expired(self, *, max_age_sec: float) -> int:
        """Drop tickets whose waiter can no longer be waiting. Caller holds the lock.

        Defence in depth: a queue that can only ever fill wedges the gateway
        permanently, so an abandoned ticket must expire rather than hold a slot
        until the process restarts.
        """
        if not self._waiting:
            return 0
        cutoff = time.time() - max_age_sec
        keep = deque(t for t in self._waiting if t.enqueued_at >= cutoff)
        reaped = len(self._waiting) - len(keep)
        if reaped:
            self._waiting = keep
        return reaped

    async def acquire(self, ticket_id: str, *, hold: bool, timeout_sec: float) -> dict[str, Any]:
        ticket = QueueTicket(ticket_id=ticket_id)
        async with self._lock:
            self._reap_expired(max_age_sec=max(timeout_sec, 1.0) * 2)
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
            # A bounced caller stops waiting the moment it receives its 503, so it
            # must never occupy a queue slot — enqueue only when the caller holds.
            position = len(self._waiting) + 1
            if not hold:
                return {
                    "ok": False,
                    "reason": "busy",
                    "queue_position": position,
                    "retry_after_sec": min(60, max(5, position * 10)),
                }
            ticket.position = position
            self._waiting.append(ticket)
        try:
            await asyncio.wait_for(ticket.event.wait(), timeout=timeout_sec)
        except asyncio.TimeoutError:
            handed_off = False
            async with self._lock:
                try:
                    self._waiting.remove(ticket)
                except ValueError:
                    # release() already popped this ticket and handed it the active
                    # slot; give that slot back instead of stranding it.
                    handed_off = ticket.event.is_set()
            if handed_off:
                await self.release()
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
