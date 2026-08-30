"""Inference queue slot accounting.

A bounced caller stops waiting as soon as it receives its 503, so enqueuing a
ticket for it leaked a queue slot per bounce. Once MAX_QUEUE_DEPTH bounces had
accumulated the gateway answered every request with queue_full at a pinned
queue_position and never recovered without a restart.

Driven with asyncio.run rather than pytest-asyncio so the suite needs no extra
plugin in the gateway image.
"""

from __future__ import annotations

import asyncio
import time

from control_plane.config import MAX_QUEUE_DEPTH
from control_plane.queue_manager import InferenceQueue, QueueTicket


async def _busy_queue() -> InferenceQueue:
    """Queue whose single concurrent slot is already taken."""
    queue = InferenceQueue()
    first = await queue.acquire("active", hold=False, timeout_sec=1.0)
    assert first["ok"], "first caller should take the active slot directly"
    return queue


def test_bounced_requests_do_not_consume_queue_slots() -> None:
    async def body() -> None:
        queue = await _busy_queue()
        for i in range(MAX_QUEUE_DEPTH * 2):
            res = await queue.acquire(f"bounce-{i}", hold=False, timeout_sec=1.0)
            assert res["ok"] is False
            assert res["reason"] == "busy", f"bounce {i} degraded to {res['reason']}"
            assert res["queue_position"] == 1, "a bounced caller never joins the queue"
        assert await queue.depth() == 1, "only the active request should be counted"

    asyncio.run(body())


def test_queue_recovers_after_active_request_releases() -> None:
    async def body() -> None:
        queue = await _busy_queue()
        for i in range(MAX_QUEUE_DEPTH + 5):
            assert (await queue.acquire(f"b-{i}", hold=False, timeout_sec=1.0))["ok"] is False
        await queue.release()
        res = await queue.acquire("after-release", hold=False, timeout_sec=1.0)
        assert res["ok"] is True, "queue must accept work again once the slot frees"

    asyncio.run(body())


def test_holding_caller_is_handed_the_slot_on_release() -> None:
    async def body() -> None:
        queue = await _busy_queue()
        waiter = asyncio.create_task(queue.acquire("holder", hold=True, timeout_sec=5.0))
        await asyncio.sleep(0.05)
        assert await queue.depth() == 2, "holder should occupy a queue slot"
        await queue.release()
        res = await waiter
        assert res["ok"] is True
        assert "queue_wait_ms" in res

    asyncio.run(body())


def test_hold_timeout_frees_its_queue_slot() -> None:
    async def body() -> None:
        queue = await _busy_queue()
        res = await queue.acquire("timeout", hold=True, timeout_sec=0.05)
        assert res["ok"] is False
        assert res["reason"] == "queue_timeout"
        assert await queue.depth() == 1, "a timed-out holder must not keep its slot"

    asyncio.run(body())


def test_slot_handed_to_a_timed_out_holder_is_returned() -> None:
    """release() can hand the slot to a ticket whose waiter already timed out.

    Holding the lock while performing the handoff forces that interleaving
    deterministically: the waiter times out, blocks on the lock, and by the time
    it runs its cleanup the ticket is gone and its event is set. Without the fix
    the handed-off slot is never given back and every later request blocks.
    """

    async def body() -> None:
        queue = await _busy_queue()
        waiter = asyncio.create_task(queue.acquire("racing", hold=True, timeout_sec=0.05))
        await asyncio.sleep(0.02)

        async with queue._lock:
            await asyncio.sleep(0.1)  # waiter times out here, then blocks on the lock
            ticket = queue._waiting.popleft()
            ticket.event.set()  # what release() does when handing over the slot

        res = await waiter
        assert res["ok"] is False
        assert res["reason"] == "queue_timeout"
        follow_up = await queue.acquire("follow-up", hold=False, timeout_sec=1.0)
        assert follow_up["ok"] is True, "a stranded slot would block all later work"

    asyncio.run(body())


def test_abandoned_tickets_are_reaped_rather_than_wedging() -> None:
    async def body() -> None:
        queue = await _busy_queue()
        stale = time.time() - 3600
        for i in range(MAX_QUEUE_DEPTH):
            queue._waiting.append(QueueTicket(ticket_id=f"stale-{i}", enqueued_at=stale))
        res = await queue.acquire("fresh", hold=False, timeout_sec=1.0)
        assert res["reason"] != "queue_full", "stale tickets must expire, not wedge the gateway"

    asyncio.run(body())
