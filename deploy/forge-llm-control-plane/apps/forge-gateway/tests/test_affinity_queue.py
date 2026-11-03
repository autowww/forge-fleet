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


def test_estimate_wait_grows_with_depth(low_starve_queue):
    q = low_starve_queue
    q._waiters.append(  # noqa: SLF001
        type("T", (), {"lane": "local", "model": "model-b", "enqueued_at": 0})()
    )
    q._running_local = 1  # noqa: SLF001
    est = q.estimate_wait_sec(target_model="model-b", lane="local")
    assert est >= 5
