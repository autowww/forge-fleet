"""Open WebUI OpenAI-compatible external lane (ChatGPT / Gemini bridges)."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from runners.loader import load_runner_config

CHATGPT_TASKS = frozenset(
    {
        "code_generate",
        "code_repo",
        "code_complete",
        "code_review",
        "testgen",
        "reason_deep",
        "agent",
        "planner",
        "code_search",
    }
)


def external_model_for_task(task_id: str) -> str:
    cfg = load_runner_config()
    if task_id in CHATGPT_TASKS:
        return cfg.external.chatgpt_model
    return cfg.external.gemini_model


def openwebui_base_url() -> str:
    env = (os.environ.get("FORGE_LLM_OPENWEBUI_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    cfg = load_runner_config()
    return cfg.external.openwebui_base_url.rstrip("/")


def is_external_model(model: str) -> bool:
    cfg = load_runner_config()
    return model in (
        cfg.external.chatgpt_model,
        cfg.external.gemini_model,
    ) or model.startswith("granite-chatgpt") or model.startswith("granite-gemini")


async def openai_chat_via_openwebui(
    *,
    model: str,
    body: dict[str, Any],
    timeout: float = 600.0,
) -> tuple[int, bytes, dict[str, str]]:
    base = openwebui_base_url()
    if not base:
        return 503, b'{"error":"openwebui_base_url not configured"}', {"content-type": "application/json"}
    url = f"{base}/v1/chat/completions"
    payload = {**body, "model": model}
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = (os.environ.get("FORGE_LLM_OPENWEBUI_API_KEY") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30.0)) as client:
        r = await client.post(url, content=json.dumps(payload).encode(), headers=headers)
        hdrs = {k.lower(): v for k, v in r.headers.items()}
        return r.status_code, r.content, hdrs
