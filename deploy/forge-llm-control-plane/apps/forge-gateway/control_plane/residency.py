"""Probe runner for models loaded in RAM."""

from __future__ import annotations

from runners.factory import get_adapter


async def resident_models() -> list[str]:
    adapter = get_adapter()
    return await adapter.resident_models()
