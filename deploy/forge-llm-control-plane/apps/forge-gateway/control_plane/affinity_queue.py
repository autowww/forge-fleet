"""Resident-first GPU queue with coalesce, starvation, and wait hints."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from control_plane.config import MAX_QUEUE_DEPTH
from control_plane.slot_manager import slot_state
from runners.loader import load_runner_config

ADEQUATE_FITS = frozenset({"candidate", "tight_or_offload", "legacy_resident", "legacy"})


@dataclass
class QueueTicket:
    ticket_id: str
    model: str
    lane: str
    enqueued_at: float = field(default_factory=time.time)
    event: asyncio.Event = field(default_factory=asyncio.Event)
    position: int = 0


class AffinityQueue:
    def __init__(self) -> None:
        self._waiters: list[QueueTicket] = []
        self._lock = asyncio.Lock()
        self._running_local = 0
        self._max_local = 1
        self._external_sem: asyncio.Semaphore | None = None
        self._p50_infer_ms = 5000.0

    def _cfg(self):
        return load_runner_config()

    def _max_for_model(self, model: str) -> int:
        cfg = self._cfg()
        if cfg.kind == "vllm":
            return max(1, int(cfg.runtime.get("OLLAMA_NUM_PARALLEL") or 4))
        if cfg.kind == "ollama":
            par = cfg.runtime.get("OLLAMA_NUM_PARALLEL")
            if par:
                try:
                    return max(1, int(par))
                except ValueError:
                    pass
        return 1

    def _external_pool(self) -> asyncio.Semaphore:
        cfg = self._cfg()
        if self._external_sem is None:
            self._external_sem = asyncio.Semaphore(cfg.external.max_concurrent)
        return self._external_sem

    def record_infer_ms(self, ms: int) -> None:
        if ms > 0:
            self._p50_infer_ms = self._p50_infer_ms * 0.8 + ms * 0.2

    async def depth(self) -> int:
        async with self._lock:
            return len(self._waiters) + self._running_local

    def _resident_model(self) -> str | None:
        if slot_state.active_model:
            return slot_state.active_model
        return None

    def _pick_next(self) -> QueueTicket | None:
        if not self._waiters:
            return None
        cfg = self._cfg()
        resident = self._resident_model()
        local = [w for w in self._waiters if w.lane == "local"]
        if not local:
            return min(self._waiters, key=lambda w: w.enqueued_at)

        if resident:
            same = [w for w in local if w.model == resident]
            if same:
                return min(same, key=lambda w: w.enqueued_at)

        now = time.time()
        starved = [w for w in local if now - w.enqueued_at >= cfg.starve_sec]
        if starved:
            return min(starved, key=lambda w: w.enqueued_at)

        if resident:
            same = [w for w in local if w.model == resident]
            if same:
                return min(same, key=lambda w: w.enqueued_at)
            pending_resident = [w for w in local if w.model != resident]
            if pending_resident:
                oldest_other = min(pending_resident, key=lambda w: w.enqueued_at)
                if now - oldest_other.enqueued_at < cfg.coalesce_sec:
                    return None

        return min(local, key=lambda w: w.enqueued_at)

    def estimate_wait_sec(self, *, target_model: str, lane: str) -> int:
        if lane == "external":
            return 5
        resident = self._resident_model()
        waiters = list(self._waiters)
        running = self._running_local
        same = sum(1 for w in waiters if w.lane == "local" and w.model == target_model)
        ahead = 0
        if resident and resident != target_model:
            ahead = sum(1 for w in waiters if w.lane == "local" and w.model == resident)
            ahead += running if running else 0
            swap = 45
        else:
            swap = 0
        per = max(1, int(self._p50_infer_ms / 1000))
        return min(600, max(5, swap + (same + ahead + running) * per))

    async def acquire(
        self,
        ticket_id: str,
        *,
        model: str,
        lane: str,
        hold: bool,
        timeout_sec: float,
    ) -> dict[str, Any]:
        if lane == "external":
            sem = self._external_pool()
            try:
                await asyncio.wait_for(
                    sem.acquire(),
                    timeout=timeout_sec if hold else 0.05,
                )
            except asyncio.TimeoutError:
                return {
                    "ok": False,
                    "reason": "busy",
                    "queue_position": 1,
                    "retry_after_sec": 10,
                }
            return {"ok": True, "queue_wait_ms": 0, "external_sem": True}

        ticket = QueueTicket(ticket_id=ticket_id, model=model, lane=lane)
        async with self._lock:
            if len(self._waiters) >= MAX_QUEUE_DEPTH:
                return {
                    "ok": False,
                    "reason": "queue_full",
                    "queue_position": len(self._waiters),
                    "retry_after_sec": 30,
                }
            ticket.position = len(self._waiters) + 1
            self._waiters.append(ticket)
            self._max_local = self._max_for_model(model)

        if not hold:
            est = self.estimate_wait_sec(target_model=model, lane=lane)
            return {
                "ok": False,
                "reason": "busy",
                "queue_position": ticket.position,
                "retry_after_sec": est,
            }

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            async with self._lock:
                nxt = self._pick_next()
                if (
                    nxt is ticket
                    and self._running_local < self._max_local
                ):
                    self._waiters.remove(ticket)
                    self._running_local += 1
                    wait_ms = int((time.time() - ticket.enqueued_at) * 1000)
                    return {"ok": True, "queue_wait_ms": wait_ms}
                for i, w in enumerate(self._waiters):
                    w.position = i + 1
            try:
                await asyncio.wait_for(ticket.event.wait(), timeout=min(2.0, deadline - time.time()))
            except asyncio.TimeoutError:
                pass
            ticket.event.clear()

        async with self._lock:
            try:
                self._waiters.remove(ticket)
            except ValueError:
                pass
        return {
            "ok": False,
            "reason": "queue_timeout",
            "queue_position": ticket.position,
            "retry_after_sec": 15,
        }

    async def release(self, *, lane: str = "local") -> None:
        if lane == "external":
            sem = self._external_pool()
            sem.release()
            return
        async with self._lock:
            self._running_local = max(0, self._running_local - 1)
            for w in self._waiters:
                w.event.set()


affinity_queue = AffinityQueue()
inference_queue = affinity_queue
