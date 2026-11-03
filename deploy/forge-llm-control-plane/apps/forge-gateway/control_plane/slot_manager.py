"""Single-slot model manager with sticky window."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from control_plane.config import STICKY_WINDOW_SEC
from runners.factory import get_adapter


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


async def ensure_model(model: str, mode: str) -> tuple[bool, bool, str | None]:
    """
    Ensure ``model`` is active. Returns (ready, swapped, error).
    """
    adapter = get_adapter()
    async with slot_state._lock:
        if slot_state.swapping and slot_state.swap_target != model:
            return False, False, "model_swap_in_progress"
        if slot_state.active_model == model and slot_state.sticky_valid():
            return True, False, None
        swapped = slot_state.active_model is not None and slot_state.active_model != model
        if swapped and adapter.config.exclusive_slot and slot_state.active_model:
            prev = slot_state.active_model
        else:
            prev = None
        slot_state.swapping = True
        slot_state.swap_target = model
    if prev:
        await adapter.unload(prev)
    try:
        ok, err = await adapter.warm(model)
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
