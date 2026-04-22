"""Bundled copy of the host CPU probe — keep in sync with ``forge-lenses/lenses/sandbox/host_cpu_probe.py``."""

from __future__ import annotations

import json
import os
import time
from typing import Any


def sample_host_cpu_usage_pct(proc_root: str, *, interval_s: float = 0.12) -> float:
    root = os.path.abspath(proc_root)

    def sample() -> tuple[int, int]:
        path = os.path.join(root, "stat")
        with open(path, encoding="utf-8") as f:
            line = f.readline()
        parts = line.split()
        if len(parts) < 5 or parts[0] != "cpu":
            raise ValueError("unexpected_cpu_line")
        nums = [int(x) for x in parts[1:]]
        idle = nums[3] + nums[4]
        total = sum(nums)
        return idle, total

    idle1, total1 = sample()
    time.sleep(float(interval_s))
    idle2, total2 = sample()
    didle = idle2 - idle1
    dtotal = total2 - total1
    if dtotal <= 0:
        return 0.0
    busy = dtotal - didle
    return max(0.0, min(100.0, 100.0 * busy / dtotal))


def run_probe() -> dict[str, Any]:
    root = str(os.environ.get("HOST_PROC_ROOT") or "/host/proc").strip() or "/host/proc"
    slot_raw = os.environ.get("FLEET_SLOT", "0")
    try:
        slot = int(slot_raw)
    except ValueError:
        slot = 0
    pct = sample_host_cpu_usage_pct(root)
    return {
        "ok": True,
        "cpu_usage_pct": round(pct, 2),
        "slot": slot,
        "proc_root": root,
    }


def main() -> None:
    try:
        out = run_probe()
        print(json.dumps(out, sort_keys=True))
    except Exception as e:  # noqa: BLE001 — surface any mount/parse error as one JSON line for Fleet job stdout
        print(
            json.dumps(
                {"ok": False, "error": str(e), "error_type": type(e).__name__},
                sort_keys=True,
            ),
            flush=True,
        )
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
