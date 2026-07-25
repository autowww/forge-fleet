"""OpenAI /v1 surface and LLM analytics routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from control_plane.classifier import resolve_mode
from control_plane.config import (
    DEFAULT_HOLD_TIMEOUT_SEC,
    OLLAMA_BASE,
    QUARANTINED_MODELS,
)
from control_plane.context import ForgeContext
from control_plane.finops import suggestions
from control_plane.modes import (
    DEFAULT_WAIT_BY_MODE,
    ModeId,
    needs_think_false,
    normalize_mode,
)
from control_plane.queue_manager import inference_queue
from control_plane.slot_manager import active_snapshot, ensure_model
from control_plane.store import (
    get_job,
    insert_feedback,
    insert_job,
    insert_request,
    list_requests,
    stats_since,
    update_job,
)
from control_plane.webhooks import deliver_webhook

router = APIRouter()


def _inject_think_false(body: dict[str, Any], model: str) -> dict[str, Any]:
    if not needs_think_false(model):
        return body
    out = dict(body)
    if "think" not in out:
        out["think"] = False
    return out


def _fingerprint(body: dict[str, Any]) -> str:
    msgs = body.get("messages") or []
    text = json.dumps(msgs, sort_keys=True)[:4000]
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def _ollama_openai(
    method: str,
    path: str,
    body: bytes,
    *,
    timeout: float = 600.0,
) -> httpx.Response:
    url = f"{OLLAMA_BASE}{path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=30.0)) as client:
        return await client.request(
            method,
            url,
            content=body,
            headers={"Content-Type": "application/json"},
        )


async def _run_chat_job(
    job_id: str,
    body: dict[str, Any],
    ctx: ForgeContext,
    resolution_mode: ModeId,
    model: str,
) -> None:
    update_job(job_id, status="running")
    t0 = time.perf_counter()
    try:
        ready, swapped, err = await ensure_model(model, resolution_mode)
        if not ready:
            update_job(job_id, status="failed", error=err or "model_unavailable")
            return
        proxied = _inject_think_false({**body, "model": model}, model)
        r = await _ollama_openai("POST", "/v1/chat/completions", json.dumps(proxied).encode())
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400:
            update_job(job_id, status="failed", error=r.text[:500], completed_ts=time.time())
        else:
            update_job(
                job_id,
                status="completed",
                response=data,
                completed_ts=time.time(),
            )
        if ctx.webhook_url and ctx.webhook_secret:
            payload = {
                "job_id": job_id,
                "status": "completed" if r.status_code < 400 else "failed",
                "mode": resolution_mode,
                "model": model,
                "response": data if r.status_code < 400 else None,
                "error": None if r.status_code < 400 else r.text[:500],
            }
            await deliver_webhook(ctx.webhook_url, ctx.webhook_secret, payload)
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": resolution_mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "swap": swapped,
                "total_ms": int((time.perf_counter() - t0) * 1000),
                "http_status": r.status_code,
                "ok": r.status_code < 400,
                "trace_id": ctx.trace_id,
                "prompt_fingerprint": _fingerprint(body),
                "meta": {"async": True, "job_id": job_id},
            }
        )
    except Exception as exc:  # noqa: BLE001
        update_job(job_id, status="failed", error=str(exc)[:500], completed_ts=time.time())


@router.post("/v1/llm/classify-mode")
async def classify_mode(request: Request) -> dict[str, Any]:
    raw = await request.json()
    ctx = ForgeContext.from_headers(dict(request.headers))
    body = raw.get("body") if isinstance(raw.get("body"), dict) else raw
    path = str(raw.get("path") or "/v1/chat/completions")
    res = await resolve_mode(
        header_mode=ctx.mode,
        body_mode=raw.get("forge_mode"),
        path=path,
        body=body,
        consumer=ctx.consumer,
    )
    return {
        "mode": res.mode,
        "model": res.model,
        "source": res.source,
    }


@router.get("/v1/llm/active")
async def llm_active() -> dict[str, Any]:
    depth = await inference_queue.depth()
    snap = active_snapshot()
    snap["queue_depth"] = depth
    return snap


@router.get("/v1/llm/stats")
async def llm_stats(hours: float = 1.0) -> dict[str, Any]:
    since = time.time() - hours * 3600
    return {
        "window_hours": hours,
        "rollup": stats_since(since),
        "active": active_snapshot(),
        "queue_depth": await inference_queue.depth(),
    }


@router.get("/v1/llm/requests")
async def llm_requests(hours: float = 24.0, limit: int = 100) -> dict[str, Any]:
    since = time.time() - hours * 3600
    return {"requests": list_requests(since, limit=min(limit, 500))}


@router.get("/v1/llm/finops/suggestions")
async def llm_finops_suggestions(hours: float = 24.0) -> dict[str, Any]:
    return {"suggestions": suggestions(since_hours=hours)}


@router.post("/v1/llm/feedback")
async def llm_feedback(request: Request) -> dict[str, str]:
    payload = await request.json()
    insert_feedback(payload)
    return {"status": "ok"}


@router.get("/v1/llm/jobs/{job_id}")
async def llm_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    out = dict(job)
    if out.get("response_json"):
        out["response"] = json.loads(out.pop("response_json"))
    if out.get("request_json"):
        out["request"] = json.loads(out.pop("request_json"))
    return out


@router.get("/v1/models")
async def openai_models() -> dict[str, Any]:
    r = await _ollama_openai("GET", "/v1/models", b"")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text[:500])
    return r.json()


@router.post("/v1/embeddings")
async def openai_embeddings(request: Request) -> Response:
    body_bytes = await request.body()
    ctx = ForgeContext.from_headers(dict(request.headers))
    try:
        body = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    res = await resolve_mode(
        header_mode=ctx.mode or "embed",
        body_mode=body.get("forge_mode"),
        path="/v1/embeddings",
        body=body,
        consumer=ctx.consumer,
    )
    model = res.model
    if model in QUARANTINED_MODELS:
        raise HTTPException(status_code=400, detail=f"Model quarantined: {model}")
    wait = ctx.wait or DEFAULT_WAIT_BY_MODE.get(res.mode, "bounce")
    ticket = str(uuid.uuid4())
    q = await inference_queue.acquire(
        ticket, hold=(wait == "hold"), timeout_sec=float(DEFAULT_HOLD_TIMEOUT_SEC)
    )
    if not q.get("ok"):
        return JSONResponse(
            {
                "error": {
                    "message": "LLM queue busy",
                    "type": "queue_busy",
                    "code": q.get("reason"),
                    "queue_position": q.get("queue_position"),
                }
            },
            status_code=503,
            headers={
                "Retry-After": str(q.get("retry_after_sec", 30)),
                "X-Forge-Queue-Position": str(q.get("queue_position", 0)),
            },
        )
    t0 = time.perf_counter()
    try:
        ready, swapped, err = await ensure_model(model, res.mode)
        if not ready:
            raise HTTPException(status_code=503, detail=err or "model unavailable")
        proxied = {**body, "model": model}
        r = await _ollama_openai("POST", "/v1/embeddings", json.dumps(proxied).encode())
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": res.mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "swap": swapped,
                "queue_wait_ms": q.get("queue_wait_ms", 0),
                "total_ms": int((time.perf_counter() - t0) * 1000),
                "http_status": r.status_code,
                "ok": r.status_code < 400,
                "trace_id": ctx.trace_id,
                "prompt_fingerprint": _fingerprint(body) if body else None,
            }
        )
        return Response(content=r.content, status_code=r.status_code, media_type="application/json")
    finally:
        await inference_queue.release()


@router.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    body_bytes = await request.body()
    ctx = ForgeContext.from_headers(dict(request.headers))
    try:
        body = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    res = await resolve_mode(
        header_mode=ctx.mode,
        body_mode=body.get("forge_mode"),
        path="/v1/chat/completions",
        body=body,
        consumer=ctx.consumer,
    )
    model = res.model
    if model in QUARANTINED_MODELS:
        raise HTTPException(status_code=400, detail=f"Model quarantined: {model}")

    if ctx.async_job:
        if not ctx.webhook_url or not ctx.webhook_secret:
            raise HTTPException(
                status_code=400,
                detail="Async jobs require X-Forge-Webhook-Url and X-Forge-Webhook-Secret",
            )
        job_id = insert_job(
            {
                "consumer": ctx.consumer,
                "mode": res.mode,
                "model": model,
                "webhook_url": ctx.webhook_url,
                "webhook_secret": ctx.webhook_secret,
                "request": body,
            }
        )
        background_tasks.add_task(
            _run_chat_job, job_id, body, ctx, res.mode, model
        )
        return JSONResponse(
            {"job_id": job_id, "status": "queued"},
            status_code=202,
            headers={"X-Forge-Job-Id": job_id},
        )

    wait = ctx.wait or DEFAULT_WAIT_BY_MODE.get(res.mode, "bounce")
    ticket = str(uuid.uuid4())
    q = await inference_queue.acquire(
        ticket, hold=(wait == "hold"), timeout_sec=float(DEFAULT_HOLD_TIMEOUT_SEC)
    )
    if not q.get("ok"):
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": res.mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "http_status": 503,
                "ok": False,
                "error_class": q.get("reason"),
                "trace_id": ctx.trace_id,
                "meta": {"bounced": True, "queue_position": q.get("queue_position")},
            }
        )
        return JSONResponse(
            {
                "error": {
                    "message": "LLM queue busy",
                    "type": "queue_busy",
                    "code": q.get("reason"),
                    "queue_position": q.get("queue_position"),
                }
            },
            status_code=503,
            headers={
                "Retry-After": str(q.get("retry_after_sec", 30)),
                "X-Forge-Queue-Position": str(q.get("queue_position", 0)),
                "X-Forge-Wait": wait,
            },
        )

    t0 = time.perf_counter()
    infer_t0 = t0
    try:
        ready, swapped, err = await ensure_model(model, res.mode)
        if not ready:
            raise HTTPException(status_code=503, detail=err or "model unavailable")
        proxied = _inject_think_false({**body, "model": model}, model)
        infer_t0 = time.perf_counter()
        r = await _ollama_openai(
            "POST",
            "/v1/chat/completions",
            json.dumps(proxied).encode(),
            timeout=float(body.get("timeout") or DEFAULT_HOLD_TIMEOUT_SEC),
        )
        tin = tout = 0
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                data = r.json()
                usage = data.get("usage") or {}
                tin = int(usage.get("prompt_tokens") or 0)
                tout = int(usage.get("completion_tokens") or 0)
            except json.JSONDecodeError:
                data = None
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": res.mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "swap": swapped,
                "queue_wait_ms": q.get("queue_wait_ms", 0),
                "infer_ms": int((time.perf_counter() - infer_t0) * 1000),
                "total_ms": int((time.perf_counter() - t0) * 1000),
                "prompt_tokens": tin,
                "completion_tokens": tout,
                "http_status": r.status_code,
                "ok": r.status_code < 400,
                "trace_id": ctx.trace_id,
                "prompt_fingerprint": _fingerprint(body),
                "meta": {"mode_source": res.source},
            }
        )
        headers = {
            "X-Forge-Llm-Mode": res.mode,
            "X-Forge-Served-Model": model,
            "X-Forge-Mode-Source": res.source,
        }
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type=r.headers.get("content-type", "application/json"),
            headers=headers,
        )
    finally:
        await inference_queue.release()
