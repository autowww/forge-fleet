"""Composer and Grok stay on the CLI lane."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.cli_lane import (  # noqa: E402
    build_cursor_argv,
    cli_model_id,
    is_cli_model,
    normalize_model,
    parse_forge_cursor,
    run_cursor_agent,
    validate_workspace,
)


def test_composer_and_grok_are_cli_not_ollama():
    assert is_cli_model("composer")
    assert is_cli_model("composer-2.5")
    assert is_cli_model("forge-llm.composer")
    assert is_cli_model("grok")
    assert is_cli_model("grok-4.7-high")
    assert not is_cli_model("qwen3.5:2b-q4_K_M")
    assert normalize_model("forge-llm.composer") == "composer"
    assert cli_model_id("composer") == "composer-2.5"
    assert cli_model_id("grok") == "grok"


def test_build_cursor_argv_agent_force():
    ws = Path("/tmp/forge-llm-cli")
    ask = build_cursor_argv(
        binary="cursor-agent",
        model="composer-2.5",
        workspace=ws,
        prompt="hi",
        forge_cursor={"mode": "ask", "force": False, "output_format": "text"},
    )
    assert "--force" not in ask
    assert "--mode" in ask and "ask" in ask
    agent = build_cursor_argv(
        binary="cursor-agent",
        model="composer-2.5",
        workspace=ws,
        prompt="hi",
        forge_cursor={"mode": "agent", "force": True, "output_format": "text"},
    )
    assert "--force" in agent


@patch("control_plane.cli_lane.subprocess.run")
def test_run_cursor_agent_bad_workspace(mock_run):
    body = {"forge_cursor": {"workspace": "/etc/passwd"}}
    with patch.dict(os.environ, {"FORGE_LLM_CLI_WORKSPACE_ROOTS": "/tmp/forge-llm-cli"}):
        status, _, _ = run_cursor_agent([{"role": "user", "content": "x"}], "composer", 30.0, body)
    assert status == 400
    mock_run.assert_not_called()


def test_parse_forge_cursor_defaults():
    fc = parse_forge_cursor({})
    assert fc["mode"] == "ask"
    assert fc["force"] is False


def test_validate_workspace_under_root(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setenv("FORGE_LLM_CLI_WORKSPACE_ROOTS", str(root))
    target, err = validate_workspace(str(root))
    assert err is None
    assert target == root.resolve()