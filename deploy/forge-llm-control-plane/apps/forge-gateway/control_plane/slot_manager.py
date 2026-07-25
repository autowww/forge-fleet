"""Single-slot Ollama model manager with sticky window."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from control_plane.config import OLLAMA_BASE, STICKY_WINDOW_SEC


@dataclass
class SlotState:
    active_model: str | None = None
    active_mode: str | None = None
    loaded_at: float = 0.0
    swapping: bool = False
    swap_target: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def sticky_valid(self) -> bool:
        if not self.active_model:
            return False
        return (time.time() - self.loaded_at) < STICKY_WINDOW_SEC


slot_state = SlotState()


async def warm_model(model: str) -> tuple[bool, str | None]:
    """Load model via minimal generate call."""
    url = f"{OLLAMA_BASE}/api/generate"
    payload = {
        "model": model,
        "prompt": "ping",
        "stream": False,
        "options": {"num_predict": 1, "num_ctx": 512},
    }
    if "qwen" in model.lower():
        payload["think"] = False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            r = await client.post(url, json=payload)
            if r.status_code >= 400:
                return False, r.text[:500]
    except httpx.RequestError as exc:
        return False, str(exc)[:500]
    return True, None


async def ensure_model(model: str, mode: str) -> tuple[bool, bool, str | None]:
    """
    Ensure ``model`` is active. Returns (ready, swapped, error).
    """
    async with slot_state._lock:
        if slot_state.swapping and slot_state.swap_target != model:
            return False, False, "model_swap_in_progress"
        if slot_state.active_model == model and slot_state.sticky_valid():
            return True, False, None
        swapped = slot_state.active_model is not None and slot_state.active_model != model
        slot_state.swapping = True
        slot_state.swap_target = model
    try:
        ok, err = await warm_model(model)
    finally:
        async with slot_state._lock:
            slot_state.swapping = False
            slot_state.swap_target = None
    if not ok:
        return False, swapped, err
    async with slot_state._lock:
        slot_state.active_model = model
        slot_state.active_mode = mode
        slot_state.loaded_at = time.time()
    return True, swapped, None


def active_snapshot() -> dict[str, Any]:
    return {
        "active_model": slot_state.active_model,
        "active_mode": slot_state.active_mode,
        "loaded_at": slot_state.loaded_at,
        "sticky_valid": slot_state.sticky_valid(),
        "swapping": slot_state.swapping,
        "swap_target": slot_state.swap_target,
        "sticky_window_sec": STICKY_WINDOW_SEC,
    }
