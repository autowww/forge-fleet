"""CLI lane request telemetry."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.context import ForgeContext  # noqa: E402
from control_plane.request_telemetry import record_cli_completion  # noqa: E402


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORGE_LLM_DB_PATH", os.path.join(td, "t.sqlite"))
        yield


def test_record_cli_completion_inserts_lane_cli(temp_db):
    from control_plane.store import list_requests

    ctx = ForgeContext(
        consumer="e2-test",
        consumer_class="remote",
        mode=None,
        wait=None,
        trace_id="t1",
        async_job=False,
        webhook_url="",
        webhook_secret="",
    )
    body = {"model": "composer", "messages": [{"role": "user", "content": "hi"}]}
    content = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    record_cli_completion(
        ctx=ctx,
        body=body,
        model="composer",
        status=200,
        content=content,
        t0=time.perf_counter(),
        served_model="composer-2.5",
    )
    rows = list_requests(time.time() - 60, limit=5)
    assert rows
    meta = json.loads(rows[0].get("meta_json") or "{}")
    assert meta.get("lane") == "cli"
    assert rows[0]["consumer"] == "e2-test"


def test_cli_requires_async_agent_mode():
    from control_plane.cli_lane import cli_requires_async

    assert cli_requires_async({"forge_cursor": {"mode": "agent"}})
    assert not cli_requires_async({"messages": [], "timeout": 30})