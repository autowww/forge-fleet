"""Cursor CLI model catalog and /v1/models merge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from control_plane.cli_catalog import (  # noqa: E402
    catalog_for_api,
    cursor_openai_model_objects,
    is_any_cli_model,
    resolve_cursor_model_id,
)


def test_composer_maps_to_25():
    assert resolve_cursor_model_id("composer") == "composer-2.5"
    assert resolve_cursor_model_id("forge-llm.composer-2.5") == "composer-2.5"


def test_catalog_lists_gpt_codex():
    assert is_any_cli_model("gpt-5.3-codex")
    assert resolve_cursor_model_id("gpt-5.3-codex") == "gpt-5.3-codex"
    assert not is_any_cli_model("qwen3.5:2b-q4_K_M")


def test_models_payload_includes_cli():
    out = cursor_openai_model_objects([])
    ids = {m["id"] for m in out}
    assert "composer-2.5" in ids
    assert any(m.get("forge_cursor_lane") for m in out)


def test_catalog_api_shape():
    payload = catalog_for_api()
    assert payload.get("endpoints", {}).get("chat_completions")
    assert any(m.get("gateway_id") == "composer-2.5" for m in payload.get("models", []))