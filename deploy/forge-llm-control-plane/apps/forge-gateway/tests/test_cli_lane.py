"""Composer stays on the CLI lane and never looks like an Ollama tag."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.cli_lane import is_cli_model, normalize_model, cli_model_id  # noqa: E402


def test_composer_is_cli_not_ollama():
    assert is_cli_model("composer")
    assert is_cli_model("composer-2.5")
    assert is_cli_model("forge-llm.composer")
    assert not is_cli_model("qwen3.5:2b-q4_K_M")
    assert normalize_model("forge-llm.composer") == "composer"
    assert cli_model_id("composer") == "composer-2.5"
    assert cli_model_id("composer-2.5") == "composer-2.5"
