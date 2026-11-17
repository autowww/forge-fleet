#!/usr/bin/env python3
"""Drain FORGE_LLM_CLI_QUEUE_DIR and run cursor-agent for queued gateway CLI jobs."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.cli_lane import normalize_model, run_cursor_agent  # noqa: E402


def _paths() -> tuple[Path, Path]:
    root = Path(os.environ.get("FORGE_LLM_CLI_QUEUE_DIR", "/data/cli-queue"))
    results = Path(os.environ.get("FORGE_LLM_CLI_RESULT_DIR", "/data/cli-result"))
    root.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    return root, results


def _process_one(queue_file: Path, results: Path) -> bool:
    try:
        payload = json.loads(queue_file.read_text())
    except (OSError, ValueError):
        queue_file.unlink(missing_ok=True)
        return False
    qid = str(payload.get("id") or queue_file.stem)
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    model = str(payload.get("model") or body.get("model") or "composer")
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    timeout = float(body.get("timeout") or body.get("forge_cursor", {}).get("timeout_s") or 600.0)
    status, content, _hdrs = run_cursor_agent(
        messages,
        normalize_model(model) or model,
        timeout,
        body,
    )
    out = results / f"{qid}.json"
    out.write_text(
        json.dumps(
            {
                "status": status,
                "content": content.decode(errors="replace"),
            }
        ),
        encoding="utf-8",
    )
    queue_file.unlink(missing_ok=True)
    return True


def main() -> None:
    poll = float(os.environ.get("FORGE_LLM_CLI_QUEUE_POLL_S", "0.5"))
    root, results = _paths()
    while True:
        jobs = sorted(root.glob("*.json"))
        if not jobs:
            time.sleep(poll)
            continue
        for job in jobs:
            try:
                _process_one(job, results)
            except Exception:  # noqa: BLE001
                err = results / f"{job.stem}.json"
                err.write_text(
                    json.dumps({"status": 502, "content": '{"error":{"message":"worker failed"}}'}),
                    encoding="utf-8",
                )
                job.unlink(missing_ok=True)


if __name__ == "__main__":
    main()