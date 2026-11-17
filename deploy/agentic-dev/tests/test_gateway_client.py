"""Gateway client for agentic-dev (mocked HTTP)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gateway_client import run_cursor_via_gateway, via_gateway_enabled  # noqa: E402


def test_via_gateway_flag():
    with patch.dict("os.environ", {"FORGE_AGENT_VIA_GATEWAY": "1"}):
        assert via_gateway_enabled()


@patch("gateway_client.urllib.request.urlopen")
def test_sync_completion(mock_urlopen):
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "done"}}]}
    ).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp
    with patch.dict(
        "os.environ",
        {
            "FORGE_LLM_BASE_URL": "http://127.0.0.1:18080/v1",
            "FORGE_LLM_CLI_ASYNC_TIMEOUT_S": "9999",
        },
        clear=False,
    ):
        result = run_cursor_via_gateway(
            model="composer-2.5",
            workspace="/tmp/forge-llm-cli",
            prompt="hello",
            timeout_s=60,
            async_job=False,
        )
    assert result.returncode == 0
    assert result.stdout == "done"