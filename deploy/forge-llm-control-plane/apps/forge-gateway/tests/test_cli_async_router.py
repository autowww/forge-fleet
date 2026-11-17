"""Async CLI jobs on chat completions."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.cli_lane import assert_cli_async_allowed  # noqa: E402
from control_plane.context import ForgeContext  # noqa: E402


def test_agent_requires_async_header():
    ctx = ForgeContext(
        consumer="x",
        consumer_class="remote",
        mode=None,
        wait=None,
        trace_id="",
        async_job=False,
        webhook_url="",
        webhook_secret="",
    )
    with pytest.raises(HTTPException) as exc:
        assert_cli_async_allowed({"forge_cursor": {"mode": "agent"}}, ctx)
    assert exc.value.status_code == 400


@patch("control_plane.router.insert_job", return_value="job-1")
@patch("control_plane.router._run_cli_job")
def test_async_cli_queues_job(mock_run, mock_insert):
    from control_plane.router import openai_chat_completions
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/chat/completions",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-forge-async", b"1"),
            (b"x-forge-webhook-url", b"https://example.com/hook"),
            (b"x-forge-webhook-secret", b"secret"),
            (b"x-forge-consumer", b"async-test"),
        ],
    }

    async def receive():
        return {
            "type": "http.request",
            "body": b'{"model":"composer","messages":[{"role":"user","content":"hi"}]}',
            "more_body": False,
        }

    request = Request(scope, receive)
    bg = BackgroundTasks()

    async def _go():
        return await openai_chat_completions(request, bg)

    import asyncio

    response = asyncio.run(_go())
    assert response.status_code == 202
    mock_insert.assert_called_once()