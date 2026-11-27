"""OpenAI-compatible HTTP bridge for Granite web-account CDP sessions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from forge_web_bridge.catalog import openai_models_payload, resolve_requested_model
from forge_web_bridge.conversation import continues_conversation, follow_up_prompt
from forge_web_bridge.tenant_cdp import resolve_cdp_for_request, tenant_uses_selector
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
    return resolve_requested_model(provider, base_id, model)


def _cdp_tabs_blocked(cdp_url: str) -> bool:
    """True when the signed-in tab is still on a Cloudflare check, so a scrape would stall."""
    import urllib.request

    base = cdp_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/json/list", timeout=2) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "page":
            continue
        blob = f"{row.get('url') or ''} {row.get('title') or ''}".lower()
        if "challenges.cloudflare.com" in blob or "just a moment" in blob:
            return True
    return False


def _live_web_model_labels(cfg: dict[str, str]) -> list[str]:
    import time as _time

    key = cfg["cdp_url"]
    if _cdp_tabs_blocked(key):
        return []
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


def _local_gemini(model: str) -> bool:
    """Use the ChatGPT bridge's own Chrome when Granite's Gemini CDP is not the path."""
    if not str(model or "").startswith("gemini-"):
        return False
    if _settings()["provider"] != "chatgpt":
        return False
    return os.getenv("FORGE_WEB_BRIDGE_GEMINI_LOCAL", "").strip().lower() in ("1", "true", "yes")


def _run_provider(
    prompt: str,
    *,
    model: str,
    cdp_url: str | None = None,
    continue_thread: bool = False,
    provider: str | None = None,
) -> str:
    """Playwright sync API hangs on the uvicorn thread. Run it in a child process."""
    cfg = _settings()
    cdp = (cdp_url or cfg["cdp_url"]).strip()
    payload = json.dumps(
        {
            "prompt": prompt,
            "model": model,
            "provider": provider or cfg["provider"],
            "cdp_url": cdp,
            "model_id": cfg["model_id"],
            "continue_thread": continue_thread,
        }
    )
    timeout_s = int(os.getenv("FORGE_WEB_BRIDGE_TIMEOUT_S", "150"))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "forge_web_bridge.run_once"],
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"provider call exceeded {timeout_s}s") from exc
    raw = (proc.stdout or "").strip()
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        detail = (proc.stderr or raw or "bridge runner returned no result")[-500:]
        raise HTTPException(status_code=502, detail=detail) from exc
    if not parsed.get("ok"):
        detail = str(parsed.get("detail") or "").strip()
        if not detail:
            detail = (proc.stderr or "bridge runner failed").strip()[-500:]
        status = int(parsed.get("status") or 502)
        extra = {}
        if parsed.get("retry_after"):
            extra["Retry-After"] = str(int(parsed["retry_after"]))
        raise HTTPException(status_code=status, detail=detail, headers=extra)
    return str(parsed.get("text") or "").strip()


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
def models(
    authorization: str | None = Header(default=None),
    x_openwebui_user_email: str | None = Header(default=None, alias="X-OpenWebUI-User-Email"),
) -> dict[str, Any]:
    _check_bearer(authorization)
    cfg = _settings()
    payload = openai_models_payload(cfg["provider"], cfg["model_id"])
    if cfg["provider"] == "chatgpt" and os.getenv("FORGE_WEB_BRIDGE_ANNOUNCE_ALL", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        gemini = openai_models_payload("gemini", "granite-gemini-primary")
        have = {row.get("id") for row in payload.get("data") or []}
        payload["data"] = list(payload.get("data") or []) + [
            row for row in gemini.get("data") or [] if row.get("id") not in have
        ]
        payload["data"].sort(
            key=lambda row: int((row.get("credits_per_1000000_tokens") or {}).get("burn_rank") or 999)
        )
    tenant_id = f"tenant-{cfg['provider']}"
    payload.setdefault("data", [])
    allowed = {tenant_id}
    if x_openwebui_user_email and (x_openwebui_user_email or "").strip():
        from forge_web_bridge.tenant_cdp import resolve_tenant_cdp

        hit = resolve_tenant_cdp(x_openwebui_user_email, cfg["provider"])
        if hit.get("connected"):
            allowed.add(tenant_id)
    if os.getenv("FORGE_WEB_BRIDGE_TENANT_ONLY", "").strip().lower() in ("1", "true", "yes"):
        payload["data"] = [row for row in payload.get("data") or [] if row.get("id") in allowed or str(row.get("id", "")).startswith("tenant-")]
    if x_openwebui_user_email and not any(str(row.get("id")) == tenant_id for row in payload.get("data") or []):
        payload["data"] = [row for row in payload.get("data") or [] if not str(row.get("id", "")).startswith("granite-")]
    return payload


def _proxy_gemini_completion(body: ChatCompletionRequest) -> str | None:
    """Send a short Gemini alias to the Gemini bridge, which still speaks the legacy id."""
    model = str(body.model or "")
    if not model.startswith("gemini-") or _settings()["provider"] != "chatgpt":
        return None
    upstream = os.getenv("FORGE_WEB_BRIDGE_GEMINI_UPSTREAM", "").strip().rstrip("/")
    if not upstream:
        return None
    bearer = os.getenv("FORGE_WEB_BRIDGE_GEMINI_UPSTREAM_BEARER", "").strip()
    choice = resolve_requested_model("gemini", "granite-gemini-primary", model)
    legacy = model
    ids = list((choice or {}).get("ids") or [])
    if len(ids) > 1:
        legacy = str(ids[1])
    messages = [item.model_dump() for item in body.messages]
    if continues_conversation(messages):
        messages = [{"role": "user", "content": follow_up_prompt(messages)}]
    payload = {
        "model": legacy,
        "messages": messages,
        "stream": False,
    }
    request = urllib.request.Request(
        f"{upstream}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise HTTPException(status_code=exc.code, detail=detail or exc.reason) from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Gemini upstream unavailable: {exc}") from exc
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="Gemini upstream returned no message") from exc


@app.post("/v1/chat/completions")
def chat_completions(
    body: ChatCompletionRequest,
    authorization: str | None = Header(default=None),
    x_forge_request_id: str | None = Header(default=None, alias=REQUEST_ID_HEADER),
    x_openwebui_user_email: str | None = Header(default=None, alias="X-OpenWebUI-User-Email"),
):
    _check_bearer(authorization)
    request_id = request_id_from(x_forge_request_id)
    headers = {REQUEST_ID_HEADER: request_id}
    local_gemini = _local_gemini(body.model or "")
    proxied = None if local_gemini else _proxy_gemini_completion(body)
    if proxied is not None:
        if body.stream:
            return StreamingResponse(
                _stream_chunks(proxied, body.model or "gemini", request_id=request_id),
                media_type="text/event-stream",
                headers=headers,
            )
        return JSONResponse(_completion_payload(proxied, body.model or "gemini", request_id=request_id), headers=headers)
    prompt = _last_user_text(body.messages)
    if not prompt:
        raise HTTPException(status_code=400, detail="messages must include a user prompt", headers=headers)
    model = body.model or _settings()["model_id"]
    cfg = _settings()
    use_tenant = tenant_uses_selector(model) or os.getenv("FORGE_WEB_BRIDGE_TENANT_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if use_tenant and not (x_openwebui_user_email or "").strip():
        raise HTTPException(
            status_code=403,
            detail="Sign in to Open WebUI with Google, then connect ChatGPT or Gemini in Lenses /setup.",
            headers=headers,
        )
    cdp_url = cfg["cdp_url"]
    if use_tenant or tenant_uses_selector(model):
        cdp_url, err = resolve_cdp_for_request(
            user_email=x_openwebui_user_email,
            model=model,
            default_provider=cfg["provider"],
            default_cdp=cfg["cdp_url"],
        )
        if err:
            raise HTTPException(status_code=403, detail=err, headers=headers)
    try:
        text = _gate.run(
            lambda: _run_provider(
                prompt,
                model=model,
                cdp_url=cdp_url,
                continue_thread=continues_conversation([item.model_dump() for item in body.messages]),
                provider="gemini" if local_gemini else None,
            )
        )
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

