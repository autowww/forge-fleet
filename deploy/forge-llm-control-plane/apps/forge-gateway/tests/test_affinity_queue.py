from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from control_plane.affinity_queue import AffinityQueue
from control_plane.slot_manager import slot_state


@pytest.fixture
def low_starve_queue(monkeypatch, tmp_path: Path):
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        "kind: ollama\nbind: 127.0.0.1:11434\nruntime: {}\nstarve_sec: 0.1\ncoalesce_sec: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    slot_state.active_model = "model-a"
    slot_state.loaded_at = 0
    q = AffinityQueue()
    yield q
    slot_state.active_model = None
    reset_runner_cache()


def test_resident_model_serviced_before_other(low_starve_queue):
    q = low_starve_queue
    order: list[str] = []

    async def worker(model: str, tag: str):
        r = await q.acquire(f"t-{tag}", model=model, lane="local", hold=True, timeout_sec=5.0)
        assert r["ok"]
        order.append(model)
        await q.release(lane="local")

    async def run():
        await asyncio.gather(
            worker("model-b", "1"),
            worker("model-a", "2"),
            worker("model-b", "3"),
        )

    asyncio.run(run())
    assert order[0] == "model-a"
    assert order.count("model-a") == 1


def test_bounce_takes_free_slot_on_idle_queue(low_starve_queue):
    """Regression: bounce (hold=False) must run immediately when a slot is free, not 503."""
    q = low_starve_queue

    async def run():
        r = await q.acquire("t-1", model="model-a", lane="local", hold=False, timeout_sec=1.0)
        assert r["ok"], r
        assert len(q._waiters) == 0  # noqa: SLF001
        # Slot now busy (max 1 for this config): a second bounce is refused and does not linger.
        r2 = await q.acquire("t-2", model="model-a", lane="local", hold=False, timeout_sec=1.0)
        assert not r2["ok"] and r2["reason"] == "busy"
        assert len(q._waiters) == 0  # noqa: SLF001
        await q.release(lane="local")
        r3 = await q.acquire("t-3", model="model-a", lane="local", hold=False, timeout_sec=1.0)
        assert r3["ok"]
        await q.release(lane="local")

    asyncio.run(run())


def test_idle_bounce_swaps_immediately_despite_coalesce(monkeypatch, tmp_path: Path):
    """Regression: resident chat model + lone embedding *bounce* request must not be refused.

    Hold-policy callers still observe the coalesce window (see
    test_resident_model_serviced_before_other)."""
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        "kind: ollama\nbind: 127.0.0.1:11434\nruntime: {}\nstarve_sec: 30\ncoalesce_sec: 5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    slot_state.active_model = "chat-model"
    try:
        q = AffinityQueue()

        async def run():
            r = await q.acquire("e-1", model="embed-model", lane="local", hold=False, timeout_sec=1.0)
            assert r["ok"], r
            # Under contention (slot busy) a second other-model bounce is still refused.
            r2 = await q.acquire("e-2", model="other-model", lane="local", hold=False, timeout_sec=1.0)
            assert not r2["ok"]
            await q.release(lane="local")

        asyncio.run(run())
    finally:
        slot_state.active_model = None
        reset_runner_cache()


def test_estimate_wait_grows_with_depth(low_starve_queue):
    q = low_starve_queue
    q._waiters.append(  # noqa: SLF001
        type("T", (), {"lane": "local", "model": "model-b", "enqueued_at": 0})()
    )
    q._running_local = 1  # noqa: SLF001
    est = q.estimate_wait_sec(target_model="model-b", lane="local")
    assert est >= 5
