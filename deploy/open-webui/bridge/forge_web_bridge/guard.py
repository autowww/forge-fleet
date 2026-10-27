"""Per-account admission control for the web bridge.

One bridge process fronts exactly one signed-in web tab, which can only answer one
prompt at a time. `InflightGate` serialises prompts, bounds the waiting queue, and
applies a wall-clock timeout to each provider call so a stuck tab cannot pin the
process. No playwright here — this module is unit-testable on its own.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")

REQUEST_ID_HEADER = "x-forge-request-id"


def env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


def env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def request_id_from(header_value: str | None) -> str:
    """Echo a sane caller-supplied id, else mint one. Never trust arbitrary bytes into logs."""
    cand = (header_value or "").strip()
    if cand and len(cand) <= 128 and all(ch.isalnum() or ch in "-_.:" for ch in cand):
        return cand
    return f"fwb_{uuid.uuid4().hex}"


class QueueFull(RuntimeError):
    pass


class ProviderTimeout(TimeoutError):
    pass


@dataclass
class GateStats:
    inflight: int
    waiting: int
    max_queue: int
    timeout_s: int


class InflightGate:
    """One in-flight call; at most `max_queue` callers waiting; each call bounded by `timeout_s`."""

    def __init__(self, *, max_queue: int, timeout_s: int) -> None:
        self.max_queue = max(0, int(max_queue))
        self.timeout_s = max(1, int(timeout_s))
        self._lock = threading.Lock()
        self._state = threading.Lock()
        self._inflight = 0
        self._waiting = 0

    @classmethod
    def from_env(cls) -> "InflightGate":
        return cls(
            max_queue=env_int("FORGE_WEB_BRIDGE_MAX_QUEUE", 4),
            timeout_s=env_int("FORGE_WEB_BRIDGE_TIMEOUT_S", 180, minimum=1),
        )

    def stats(self) -> GateStats:
        with self._state:
            return GateStats(self._inflight, self._waiting, self.max_queue, self.timeout_s)

    def run(self, fn: Callable[[], T]) -> T:
        with self._state:
            if self._inflight + self._waiting >= self.max_queue + 1:
                raise QueueFull(f"bridge queue full (max_queue={self.max_queue})")
            self._waiting += 1
        acquired = False
        try:
            self._lock.acquire()
            acquired = True
            with self._state:
                self._waiting -= 1
                self._inflight += 1
            try:
                return _call_with_timeout(fn, self.timeout_s)
            finally:
                with self._state:
                    self._inflight -= 1
        finally:
            if acquired:
                self._lock.release()
            else:
                with self._state:
                    self._waiting -= 1


def _call_with_timeout(fn: Callable[[], T], timeout_s: int) -> T:
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # propagate to caller thread
            box["error"] = exc

    worker = threading.Thread(target=_target, name="forge-web-bridge-provider", daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise ProviderTimeout(f"provider call exceeded {timeout_s}s")
    if "error" in box:
        raise box["error"]
    return box["value"]
