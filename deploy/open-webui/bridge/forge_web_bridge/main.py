"""OpenAI-compatible HTTP bridge for Granite web-account CDP sessions."""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from forge_web_bridge.catalog import catalog_row_for_slug, openai_models_payload
from forge_web_bridge.guard import (
    REQUEST_ID_HEADER,
    InflightGate,
    ProviderTimeout,
    QueueFull,
    env_flag,
    request_id_from,
)

app = FastAPI(title="forge-web-bridge", version="0.2.0")

_gate = InflightGate.from_env()

_models_cache: dict[str, tuple[float, list[str]]] = {}
_MODELS_CACHE_TTL = float(os.getenv("FORGE_WEB_BRIDGE_MODELS_CACHE_TTL", "120"))


class ChatMessage(BaseModel):
    role: str
    content: str | list[Any] = ""


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False


def _settings() -> dict[str, str]:
    return {
        "provider": os.getenv("FORGE_WEB_BRIDGE_PROVIDER", "chatgpt").strip().lower(),
        "cdp_url": os.getenv("FORGE_WEB_BRIDGE_CDP_URL", "http://127.0.0.1:9230").strip().rstrip("/"),
        "model_id": os.getenv("FORGE_WEB_BRIDGE_MODEL_ID", "granite-web-bridge").strip(),
        "bearer": os.getenv("FORGE_WEB_BRIDGE_BEARER", "").strip(),
    }


def _bearer_required() -> bool:
    """Fail closed by default: the bridge binds 0.0.0.0 on Granite so Docker can reach it."""
    return env_flag("FORGE_WEB_BRIDGE_REQUIRE_BEARER", True)


def _check_bearer(authorization: str | None) -> None:
    expected = _settings()["bearer"]
    if not expected:
        if _bearer_required():
            raise HTTPException(
                status_code=503,
                detail="bearer_not_configured: set FORGE_WEB_BRIDGE_BEARER (or FORGE_WEB_BRIDGE_REQUIRE_BEARER=0 for loopback dev)",
            )
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer")
    got = authorization.removeprefix("Bearer ").strip()
    if got != expected:
        raise HTTPException(status_code=401, detail="invalid bearer")


def _last_user_text(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role != "user":
            continue
        if isinstance(msg.content, str):
            return msg.content.strip()
        if isinstance(msg.content, list):
            parts: list[str] = []
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            return "\n".join(parts).strip()
    return ""


def _resolve_variant(provider: str, base_id: str, model: str) -> dict[str, Any] | None:
    prefix = f"{base_id}."
    if not model or model == base_id or not model.startswith(prefix):
        return None
    slug = model[len(prefix) :].strip()
    if not slug:
        return None
    row = catalog_row_for_slug(provider, slug)
    if row:
        return row
    return {"slug": slug, "label": slug.replace("-", " "), "match": [slug]}


def _live_web_model_labels(cfg: dict[str, str]) -> list[str]:
    import time as _time

    key = cfg["cdp_url"]
    now = _time.time()
    cached = _models_cache.get(key)
    if cached and (now - cached[0]) < _MODELS_CACHE_TTL:
        return cached[1]
    labels: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return labels
    provider = cfg["provider"]
    try:
        with sync_playwright() as pw:
            if provider == "chatgpt":
                from forge_lcdl.playwright.connectors.chatgpt import connect_chatgpt_tab
                from forge_lcdl.playwright.connectors.web_ui_models import list_chatgpt_web_models
                from forge_lcdl.result import Err

                attached = connect_chatgpt_tab(pw, cfg["cdp_url"])
                if isinstance(attached, Err):
                    return labels
                sess = attached.value
                try:
                    labels = list_chatgpt_web_models(sess.page)
                finally:
                    sess.close_tab()
            elif provider == "gemini":
                from forge_lcdl.playwright.connectors.gemini import connect_gemini_tab
                from forge_lcdl.playwright.connectors.web_ui_models import list_gemini_web_models
                from forge_lcdl.result import Err

                attached = connect_gemini_tab(pw, cfg["cdp_url"])
                if isinstance(attached, Err):
                    return labels
                sess = attached.value
                try:
                    labels = list_gemini_web_models(sess.page)
                finally:
                    sess.close_tab()
    except Exception:
        labels = []
    _models_cache[key] = (now, labels)
    return labels


def _run_provider(prompt: str, *, model: str) -> str:
    cfg = _settings()
    provider = cfg["provider"]
    cdp_url = cfg["cdp_url"]
    base_id = cfg["model_id"]
    variant = _resolve_variant(provider, base_id, model)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="playwright not installed; pip install 'forge-lcdl[playwright]' on Granite host",
        )

    with sync_playwright() as pw:
        if provider == "chatgpt":
            from forge_lcdl.playwright.connectors.chatgpt import connect_chatgpt_tab, send_chatgpt_prompt
            from forge_lcdl.result import Err

            attached = connect_chatgpt_tab(pw, cdp_url)
            if isinstance(attached, Err):
                raise HTTPException(status_code=503, detail=attached.error.message)
            sess = attached.value
            try:
                page_url = str(getattr(sess.page, "url", "") or "")
                if "challenges.cloudflare.com" in page_url:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "ChatGPT Cloudflare challenge on Granite — use "
                            "granite-open-webui-auth-laptop.sh chatgpt-primary (complete Turnstile) "
                            "or pack-open-webui-edge-profile.sh from a laptop session"
                        ),
                    )
                if variant:
                    from forge_lcdl.playwright.connectors.web_ui_models import select_chatgpt_web_model

                    picked = select_chatgpt_web_model(
                        sess.page,
                        label=str(variant.get("label") or variant.get("slug") or ""),
                        match=list(variant.get("match") or []),
                    )
                    if isinstance(picked, Err):
                        raise HTTPException(status_code=503, detail=picked.error.message)
                result = send_chatgpt_prompt(sess.page, prompt, min_response_chars=20)
            finally:
                sess.close_tab()
            if isinstance(result, Err):
                raise HTTPException(status_code=502, detail=result.error.message)
            return str(result.value or "").strip()

        if provider == "gemini":
            from forge_lcdl.playwright.connectors.gemini import connect_gemini_tab, send_gemini_prompt
            from forge_lcdl.result import Err

            attached = connect_gemini_tab(pw, cdp_url)
            if isinstance(attached, Err):
                raise HTTPException(status_code=503, detail=attached.error.message)
            sess = attached.value
            try:
                if variant:
                    from forge_lcdl.playwright.connectors.web_ui_models import select_gemini_web_model

                    picked = select_gemini_web_model(
                        sess.page,
                        label=str(variant.get("label") or variant.get("slug") or ""),
                        match=list(variant.get("match") or []),
                    )
                    if isinstance(picked, Err):
                        raise HTTPException(status_code=503, detail=picked.error.message)
                result = send_gemini_prompt(sess.page, prompt, min_response_chars=20)
            finally:
                sess.close_tab()
            if isinstance(result, Err):
                raise HTTPException(status_code=502, detail=result.error.message)
            return str(result.value or "").strip()

    raise HTTPException(status_code=400, detail=f"unsupported provider: {provider}")


def _completion_payload(text: str, model: str, *, request_id: str | None = None) -> dict[str, Any]:
    now = int(time.time())
    return {
        "id": f"chatcmpl-{request_id or uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": now,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


def _stream_chunks(text: str, model: str, *, request_id: str | None = None):
    chunk_id = f"chatcmpl-{request_id or uuid.uuid4().hex}"
    created = int(time.time())
    first = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(first)}\n\n".encode()
    body = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(body)}\n\n".encode()
    done = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(done)}\n\n".encode()
    yield b"data: [DONE]\n\n"


@app.get("/health")
def health() -> dict[str, Any]:
    cfg = _settings()
    st = _gate.stats()
    return {
        "ok": True,
        "provider": cfg["provider"],
        "model": cfg["model_id"],
        "cdp_url": cfg["cdp_url"],
        "bearer_configured": bool(cfg["bearer"]),
        "bearer_required": _bearer_required(),
        "inflight": st.inflight,
        "waiting": st.waiting,
        "max_queue": st.max_queue,
        "timeout_s": st.timeout_s,
    }


@app.get("/v1/models")
def models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _check_bearer(authorization)
    cfg = _settings()
    live = _live_web_model_labels(cfg)
    return openai_models_payload(cfg["provider"], cfg["model_id"], live_labels=live or None)


@app.post("/v1/chat/completions")
def chat_completions(
    body: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
    x_forge_request_id: str | None = Header(default=None, alias=REQUEST_ID_HEADER),
):
    _check_bearer(authorization)
    request_id = request_id_from(x_forge_request_id)
    headers = {REQUEST_ID_HEADER: request_id}
    prompt = _last_user_text(body.messages)
    if not prompt:
        raise HTTPException(status_code=400, detail="messages must include a user prompt", headers=headers)
    model = body.model or _settings()["model_id"]
    try:
        text = _gate.run(lambda: _run_provider(prompt, model=model))
    except QueueFull as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={**headers, "Retry-After": "5"})
    except ProviderTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc), headers=headers)
    except HTTPException as exc:
        exc.headers = {**(exc.headers or {}), **headers}
        raise
    if body.stream:
        return StreamingResponse(
            _stream_chunks(text, model, request_id=request_id),
            media_type="text/event-stream",
            headers=headers,
        )
    return JSONResponse(_completion_payload(text, model, request_id=request_id), headers=headers)


def main() -> None:
    import uvicorn

    host = os.getenv("FORGE_WEB_BRIDGE_LISTEN_HOST", "127.0.0.1")
    port = int(os.getenv("FORGE_WEB_BRIDGE_LISTEN_PORT", "9240"))
    uvicorn.run(app, host=host, port=port, log_level="info")

