"""Status and enqueue for the cursor-host ecosystem gate runner.

The runner writes ``status.json`` and drains ``enqueue.jsonl``. Fleet only
reads and appends those files. It does not call cursor-agent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def gate_root() -> Path:
    raw = str(os.environ.get("ECOSYSTEM_GATE_BASE") or "/home/leo/semi-cascade").strip()
    return Path(raw)


def status() -> dict[str, Any]:
    path = gate_root() / "status.json"
    if not path.is_file():
        return {"ok": False, "error": "ecosystem_gates_unavailable"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "ecosystem_gates_unreadable"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "ecosystem_gates_unreadable"}
    payload["ok"] = True
    return payload


def enqueue(body: dict[str, Any] | None) -> dict[str, Any]:
    ticker = str((body or {}).get("ticker") or (body or {}).get("anchor_ticker") or "").strip().upper()
    if not ticker:
        return {"ok": False, "error": "ticker is required", "http": 400}
    root = gate_root()
    root.mkdir(parents=True, exist_ok=True)
    with (root / "enqueue.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ticker": ticker}) + "\n")
    return {"ok": True, "ticker": ticker, "http": 202}
