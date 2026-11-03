from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from control_plane.context import ForgeContext
from control_plane.route_select import plan_route
from control_plane.task_resolve import TaskResolution


@pytest.fixture
def runner_with_pins(tmp_path: Path, monkeypatch):
    cat = (
        Path(__file__).resolve().parents[3]
        / "configs"
        / "catalog"
        / "forge_llm_catalog_2026-11-03.json"
    )
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        f"""
kind: ollama
bind: 127.0.0.1:11434
runtime: {{}}
free_vram_gb: 4
catalog_path: {cat}
artifact_pins:
  - runner_model_id: ctx-unlim-qwen3-8b:latest
    enabled: true
  - runner_model_id: qwen3:30b-a3b
    enabled: true
external:
  openwebui_base_url: http://127.0.0.1:19808
  chatgpt_model: granite-chatgpt-primary
  gemini_model: granite-gemini-primary
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    yield
    reset_runner_cache()


def test_remote_escalates_when_no_local_fit(runner_with_pins, monkeypatch):
    async def _empty():
        return []

    monkeypatch.setattr("control_plane.route_select.resident_models", _empty)
    task = TaskResolution("code_repo", "codegen_loop", "body_task")
    ctx = ForgeContext(
        consumer="remote-app",
        consumer_class="remote",
        mode=None,
        wait=None,
        async_job=False,
        webhook_url=None,
        webhook_secret=None,
        trace_id=None,
    )

    route = asyncio.run(plan_route(task=task, body={"messages": []}, ctx=ctx))
    assert route.lane == "external"
    assert route.model == "granite-chatgpt-primary"


def test_local_never_external(runner_with_pins, monkeypatch):
    async def _empty():
        return []

    monkeypatch.setattr("control_plane.route_select.resident_models", _empty)
    task = TaskResolution("code_repo", "codegen_loop", "body_task")
    ctx = ForgeContext(
        consumer="local-app",
        consumer_class="local",
        mode=None,
        wait=None,
        async_job=False,
        webhook_url=None,
        webhook_secret=None,
        trace_id=None,
    )
    route = asyncio.run(plan_route(task=task, body={"messages": []}, ctx=ctx))
    assert route.lane == "local"


def test_resident_kept_when_adequate(runner_with_pins, monkeypatch):
    async def _res():
        return ["ctx-unlim-qwen3-8b:latest"]

    monkeypatch.setattr("control_plane.route_select.resident_models", _res)
    task = TaskResolution("chat", "interactive", "default")
    ctx = ForgeContext(
        consumer="x",
        consumer_class="remote",
        mode=None,
        wait=None,
        async_job=False,
        webhook_url=None,
        webhook_secret=None,
        trace_id=None,
    )
    route = asyncio.run(plan_route(task=task, body={"messages": []}, ctx=ctx))
    assert route.lane == "local"
    assert route.model == "ctx-unlim-qwen3-8b:latest"
