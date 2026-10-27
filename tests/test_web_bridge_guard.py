from __future__ import annotations

import threading
import time

import pytest

from forge_web_bridge.guard import InflightGate, ProviderTimeout, QueueFull, request_id_from


def test_request_id_echo_and_mint() -> None:
    assert request_id_from("abc-123_x.y:z") == "abc-123_x.y:z"
    assert request_id_from(None).startswith("fwb_")
    assert request_id_from("bad id with spaces").startswith("fwb_")
    assert request_id_from("x" * 200).startswith("fwb_")


def test_gate_serialises_and_runs() -> None:
    gate = InflightGate(max_queue=2, timeout_s=5)
    assert gate.run(lambda: 42) == 42
    st = gate.stats()
    assert (st.inflight, st.waiting) == (0, 0)


def test_gate_rejects_when_queue_full() -> None:
    gate = InflightGate(max_queue=0, timeout_s=5)
    started = threading.Event()
    release = threading.Event()

    def slow() -> str:
        started.set()
        release.wait(5)
        return "done"

    results: dict[str, object] = {}
    t = threading.Thread(target=lambda: results.__setitem__("first", gate.run(slow)))
    t.start()
    assert started.wait(2)
    with pytest.raises(QueueFull):
        gate.run(lambda: "second")
    release.set()
    t.join(5)
    assert results["first"] == "done"


def test_gate_times_out_stuck_provider() -> None:
    gate = InflightGate(max_queue=1, timeout_s=1)
    with pytest.raises(ProviderTimeout):
        gate.run(lambda: time.sleep(3))


def test_gate_propagates_provider_errors() -> None:
    gate = InflightGate(max_queue=1, timeout_s=5)

    def boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError):
        gate.run(boom)
    assert gate.stats().inflight == 0
