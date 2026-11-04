"""Catalog bundle requirements (forge_llm_README.md routing procedure) → gateway behaviour."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

CATALOG = Path(__file__).resolve().parents[3] / "configs" / "catalog" / "forge_llm_catalog_2026-11-03.json"


@pytest.fixture
def granite_cfg(monkeypatch):
    cfg = Path(__file__).resolve().parents[3] / "configs" / "runner.granite.yaml"
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    monkeypatch.delenv("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", raising=False)
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    yield
    reset_runner_cache()


@pytest.fixture
def measured_cfg(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "runner.yaml"
    cfg.write_text(
        f"""
kind: ollama
bind: 127.0.0.1:11434
runtime: {{}}
free_vram_gb: 4
headroom_ratio: 0.15
catalog_path: {CATALOG}
max_active_requests: 2
max_queue_depth: 10
artifact_pins:
  - runner_model_id: big-chat:latest
    catalog_alias: Q2
    measured:
      peak_vram_mib: 3900     # 3900 * 1.15 > 4096 -> exceeds headroom
  - runner_model_id: small-chat:latest
    catalog_alias: MIN3
    model_revision: abc123
    weight_file_sha256: deadbeef
    runtime_probe: passed
    license_approval: true
    measured:
      peak_vram_mib: 2500
      context_length: 4096
      active_requests: 2
      p95_latency_ms: 3000
      task_quality_score: 0.8
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FORGE_LLM_RUNNER_CONFIG", str(cfg))
    monkeypatch.delenv("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", raising=False)
    from runners.loader import reset_runner_cache

    reset_runner_cache()
    yield
    reset_runner_cache()


# --- bundle integrity (mirrors test_forge_llm_catalog.py shipped in the zip) ---


def test_vendored_catalog_integrity():
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    aliases = [m["alias"] for m in cat["models"]]
    assert len(aliases) == len(set(aliases))
    assert len({m["model_id"] for m in cat["models"]}) == len(aliases)
    names = set(aliases)
    for task in cat["tasks"]:
        assert set(task["candidates_by_vram_gb"]) == set(map(str, cat["vram_tiers_gb"]))
        for cells in task["candidates_by_vram_gb"].values():
            for c in cells:
                assert c["alias"] in names
    for m in cat["models"]:
        assert m["source_url"].endswith(m["model_id"])


def test_granite_pins_cover_4gb_tier_chat_code_embedding(granite_cfg):
    """Catalog README: on Granite 4 GB use Qwen3.5-2B Q4 or specialized candidates first."""
    from control_plane.catalog_select import resolve_runner_model_for_task

    mid, alias, fit = resolve_runner_model_for_task("chat")
    assert (mid, alias, fit) == ("qwen3.5:2b", "Q2", "candidate")
    mid, alias, fit = resolve_runner_model_for_task("code_generate")
    assert (mid, alias, fit) == ("qwen2.5-coder:3b", "C3", "candidate")
    mid, alias, fit = resolve_runner_model_for_task("embedding")
    assert (mid, alias, fit) == ("qwen3-embedding:0.6b", "E06", "candidate")


def test_pin_declares_runtime_support_for_catalog_alias(granite_cfg):
    """E06 is catalogued for vLLM/transformers only; the Ollama pin is the observed-runtime evidence."""
    from control_plane.catalog_select import catalog_candidates_for_task

    rows = {c["alias"]: c for c in catalog_candidates_for_task("embedding")}
    assert "E06" in rows
    assert "runtime_support_from_pin_not_catalog" in rows["E06"]["flags"]
    assert "BM3" not in rows  # unpinned, non-llama.cpp candidate stays filtered


def test_granite_queue_policy_two_active_ten_queued(granite_cfg):
    from runners.loader import load_runner_config
    from control_plane.affinity_queue import AffinityQueue

    cfg = load_runner_config()
    assert cfg.max_active_requests == 2
    assert cfg.max_queue_depth == 10
    q = AffinityQueue()
    assert q._max_for_model("qwen3.5:2b") == 2
    assert q._max_queue_depth() == 10


def test_legacy_pins_carry_tier_note_and_are_not_authorized(granite_cfg):
    from runners.loader import load_runner_config

    cfg = load_runner_config()
    by_id = {p.runner_model_id: p for p in cfg.artifact_pins}
    assert by_id["qwen3:30b-a3b"].tier_note
    assert all(not p.deployment_authorized for p in cfg.artifact_pins)
    assert "weight_file_sha256" in by_id["qwen3.5:2b"].promotion_missing()


# --- headroom + promotion ---


def test_measured_headroom_excludes_pin(measured_cfg):
    from control_plane.catalog_select import measured_fit, pin_by_id, resolve_runner_model_for_task

    big = pin_by_id("big-chat:latest")
    small = pin_by_id("small-chat:latest")
    assert big is not None and small is not None
    assert measured_fit(big) == "exceeds_headroom"
    assert measured_fit(small) == "fits_with_headroom"
    mid, alias, fit = resolve_runner_model_for_task("chat")
    assert mid == "small-chat:latest" and alias == "MIN3"


def test_promotion_authorized_only_with_full_evidence(measured_cfg):
    from control_plane.catalog_select import pin_by_id

    small = pin_by_id("small-chat:latest")
    big = pin_by_id("big-chat:latest")
    assert small is not None and small.deployment_authorized
    assert big is not None and not big.deployment_authorized
    assert "license_approval" in big.promotion_missing()


# --- explicit model policy + language + deterministic-first ---


def _ctx(consumer_class: str = "remote", language: str | None = None):
    from control_plane.context import ForgeContext

    return ForgeContext(
        consumer="t",
        consumer_class=consumer_class,  # type: ignore[arg-type]
        mode=None,
        wait=None,
        async_job=False,
        webhook_url=None,
        webhook_secret=None,
        trace_id=None,
        language=language,
    )


def test_unpinned_explicit_model_rejected_in_pinned_only_mode(granite_cfg, monkeypatch):
    from control_plane.route_select import plan_route
    from control_plane.task_resolve import TaskResolution

    monkeypatch.setattr("control_plane.route_select.resident_models", _empty_residents)
    task = TaskResolution("chat", "interactive", "body_task")
    monkeypatch.setenv("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", "true")
    with pytest.raises(ValueError, match="model_not_pinned"):
        asyncio.run(plan_route(task=task, body={"model": "mystery:latest", "messages": []}, ctx=_ctx()))

    monkeypatch.delenv("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY")
    route = asyncio.run(plan_route(task=task, body={"model": "mystery:latest", "messages": []}, ctx=_ctx()))
    assert route.model == "mystery:latest" and route.fit == "explicit_unpinned"


def test_openwebui_prefix_is_stripped(granite_cfg, monkeypatch):
    from control_plane.route_select import plan_route
    from control_plane.task_resolve import TaskResolution

    monkeypatch.setattr("control_plane.route_select.resident_models", _empty_residents)
    task = TaskResolution("chat", "interactive", "body_task")
    route = asyncio.run(plan_route(task=task, body={"model": "forge-llm.qwen3.5:2b", "messages": []}, ctx=_ctx()))
    assert route.model == "qwen3.5:2b" and route.fit == "explicit"


def test_language_filter_excludes_incompatible_allowlist(granite_cfg, monkeypatch):
    """ASR: AS17 lists languages that exclude 'uk'; Parakeet v3 includes it."""
    from control_plane.catalog_select import catalog_candidates_for_task

    # ASR models are NeMo/transformers only; disable the runtime filter to exercise the language gate.
    monkeypatch.setattr("control_plane.catalog_select._runtime_filter", lambda _kind: None)
    uk = {c["alias"] for c in catalog_candidates_for_task("asr", free_vram_gb=8, language="uk")}
    en = {c["alias"] for c in catalog_candidates_for_task("asr", free_vram_gb=8, language="en")}
    assert "AS17" not in uk
    assert "AS17" in en


def test_deterministic_first_header_for_exact_tasks(granite_cfg):
    from control_plane.interception import _forge_route_headers

    h = _forge_route_headers(
        task_id="finance_facts", lane="local", model="m", mode="interactive", mode_source="x", resident=None
    )
    assert h["X-Forge-Deterministic-First"] == "recommended"
    h2 = _forge_route_headers(task_id="chat", lane="local", model="m", mode="interactive", mode_source="x", resident=None)
    assert "X-Forge-Deterministic-First" not in h2


async def _empty_residents():
    return []
