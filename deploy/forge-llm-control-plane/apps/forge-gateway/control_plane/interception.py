"""Shared queue / mode / warm path for OpenAI and Ollama native inference."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from control_plane.config import DEFAULT_HOLD_TIMEOUT_SEC, QUARANTINED_MODELS
from control_plane.context import ForgeContext
from control_plane.external_lane import openai_chat_via_openwebui
from control_plane.modes import DEFAULT_WAIT_BY_MODE, ModeId, needs_think_false
from control_plane.queue_manager import inference_queue
from control_plane.route_select import header_task_from_request, plan_route
from control_plane.slot_manager import active_snapshot, ensure_model
from control_plane.store import insert_request
from control_plane.task_resolve import deterministic_first_recommended, resolve_task
from control_plane.catalog_select import catalog_evidence
from runners.base import NativeApiUnsupported
from runners.factory import get_adapter
from runners.loader import config_hash


def _forge_route_headers(
    *,
    task_id: str,
    lane: str,
    model: str,
    mode: ModeId,
    mode_source: str,
    resident: str | None,
    catalog_alias: str | None = None,
    fit: str | None = None,
) -> dict[str, str]:
    out = {
        "X-Forge-Llm-Mode": mode,
        "X-Forge-Task": task_id,
        "X-Forge-Lane": lane,
        "X-Forge-Served-Model": model,
        "X-Forge-Queue-Model": model,
        "X-Forge-Mode-Source": mode_source,
        "X-Forge-Resident-Model": resident or "",
        "X-Forge-Catalog-Alias": catalog_alias or "",
        "X-Forge-Catalog-Fit": fit or "",
    }
    if deterministic_first_recommended(task_id):
        out["X-Forge-Deterministic-First"] = "recommended"
    return out


def _route_evidence(route: Any, task: Any) -> dict[str, Any]:
    """Catalog README step 8: log chosen artifact, catalog alias/fit, catalog revision, config hash."""
    ev = catalog_evidence()
    return {
        "mode_source": route.mode_source,
        "task": task.task_id,
        "lane": route.lane,
        "catalog_alias": route.catalog_alias,
        "fit": route.fit,
        "catalog_schema": ev.get("catalog_schema"),
        "catalog_date": ev.get("catalog_date"),
        "runner_config_hash": config_hash(),
        "deterministic_first": deterministic_first_recommended(task.task_id),
    }


def fingerprint_body(body: dict[str, Any]) -> str:
    msgs = body.get("messages")
    if isinstance(msgs, list):
        text = json.dumps(msgs, sort_keys=True)[:4000]
    else:
        text = json.dumps(body, sort_keys=True)[:4000]
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def inject_think_false(body: dict[str, Any], model: str, *, openai_surface: bool = False) -> dict[str, Any]:
    """
    Disable chain-of-thought by default for thinking families (qwen3*, deepseek-r1).

    Native ``/api/*`` honors ``think: false``. Ollama's OpenAI-compatible ``/v1`` surface
    ignores ``think`` (measured on 0.40.13) but honors ``reasoning_effort: "none"``; callers
    that set ``reasoning_effort`` / ``reasoning`` explicitly keep their choice.
    """
    if not needs_think_false(model):
        return body
    out = dict(body)
    if "think" not in out:
        out["think"] = False
    if openai_surface and "reasoning_effort" not in out and "reasoning" not in out:
        try:
            kind = get_adapter().kind
        except Exception:  # noqa: BLE001
            kind = "ollama"
        if kind == "ollama":
            out["reasoning_effort"] = "none"
    return out


def is_intercepted_native_path(path: str) -> bool:
    p = path.rstrip("/")
    return p in ("/api/chat", "/api/generate")


def read_only_native_path(path: str) -> bool:
    p = path.rstrip("/")
    return p.startswith("/api/tags") or p.startswith("/api/ps") or p.startswith("/api/version")


async def adapter_openai(
    method: str,
    path: str,
    body: bytes,
    *,
    timeout: float = 600.0,
) -> tuple[int, bytes, dict[str, str]]:
    adapter = get_adapter()
    return await adapter.openai_request(method, path, body, timeout=timeout)


async def run_openai_inference(
    *,
    path: str,
    body: dict[str, Any],
    ctx: ForgeContext,
    timeout: float | None = None,
    request_headers: dict[str, str] | None = None,
) -> Response:
    headers = request_headers or {}
    try:
        task = resolve_task(
            header_task=header_task_from_request(headers) or None,
            body_task=body.get("forge_task") or body.get("task_id"),
            header_mode=ctx.mode or ("embed" if path.rstrip("/") == "/v1/embeddings" else None),
            body_mode=body.get("forge_mode"),
            path=path,
            body=body,
        )
        route = await plan_route(task=task, body=body, ctx=ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    model = route.model
    res_mode = task.mode
    if model in QUARANTINED_MODELS:
        raise HTTPException(status_code=400, detail=f"Model quarantined: {model}")

    wait = ctx.wait or DEFAULT_WAIT_BY_MODE.get(res_mode, "bounce")
    ticket = str(uuid.uuid4())
    resident = active_snapshot().get("active_model")
    q = await inference_queue.acquire(
        ticket,
        model=model,
        lane=route.lane,
        hold=(wait == "hold"),
        timeout_sec=float(DEFAULT_HOLD_TIMEOUT_SEC),
    )
    if not q.get("ok"):
        retry = q.get("retry_after_sec", 30)
        if wait == "bounce":
            retry = inference_queue.estimate_wait_sec(target_model=model, lane=route.lane)
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": res_mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "http_status": 503,
                "ok": False,
                "error_class": q.get("reason"),
                "trace_id": ctx.trace_id,
                "meta": {
                    "bounced": True,
                    "queue_position": q.get("queue_position"),
                    **_route_evidence(route, task),
                },
            }
        )
        return JSONResponse(
            {
                "error": {
                    "message": "LLM queue busy",
                    "type": "queue_busy",
                    "code": q.get("reason"),
                    "queue_position": q.get("queue_position"),
                    "suggested_wait_sec": retry,
                }
            },
            status_code=503,
            headers={
                "Retry-After": str(retry),
                "X-Forge-Suggested-Wait-Sec": str(retry),
                "X-Forge-Queue-Position": str(q.get("queue_position", 0)),
                "X-Forge-Wait": wait,
                **_forge_route_headers(
                    task_id=task.task_id,
                    lane=route.lane,
                    model=model,
                    mode=res_mode,
                    mode_source=route.mode_source,
                    resident=resident,
                    catalog_alias=route.catalog_alias,
                    fit=route.fit,
                ),
            },
        )

    t0 = time.perf_counter()
    infer_t0 = t0
    swapped = False
    try:
        if route.lane == "external":
            proxied = {**body, "model": model}
            to = float(timeout or body.get("timeout") or DEFAULT_HOLD_TIMEOUT_SEC)
            status, content, hdrs = await openai_chat_via_openwebui(
                model=model, body=proxied, timeout=to
            )
        else:
            ready, swapped, err = await ensure_model(model, res_mode)
            if not ready:
                raise HTTPException(status_code=503, detail=err or "model unavailable")
            proxied = inject_think_false({**body, "model": model}, model, openai_surface=True)
            infer_t0 = time.perf_counter()
            to = float(timeout or body.get("timeout") or DEFAULT_HOLD_TIMEOUT_SEC)
            status, content, hdrs = await adapter_openai(
                "POST",
                path,
                json.dumps(proxied).encode(),
                timeout=to,
            )
        media = hdrs.get("content-type", "application/json")
        tin = tout = 0
        if media.startswith("application/json"):
            try:
                data = json.loads(content)
                usage = data.get("usage") or {}
                tin = int(usage.get("prompt_tokens") or 0)
                tout = int(usage.get("completion_tokens") or 0)
            except json.JSONDecodeError:
                pass
        infer_ms = int((time.perf_counter() - infer_t0) * 1000)
        inference_queue.record_infer_ms(infer_ms)
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": res_mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "swap": swapped,
                "queue_wait_ms": q.get("queue_wait_ms", 0),
                "infer_ms": infer_ms,
                "total_ms": int((time.perf_counter() - t0) * 1000),
                "prompt_tokens": tin,
                "completion_tokens": tout,
                "http_status": status,
                "ok": status < 400,
                "trace_id": ctx.trace_id,
                "prompt_fingerprint": fingerprint_body(body),
                "meta": {
                    **_route_evidence(route, task),
                    "path": path,
                },
            }
        )
        return Response(
            content=content,
            status_code=status,
            media_type=media,
            headers=_forge_route_headers(
                task_id=task.task_id,
                lane=route.lane,
                model=model,
                mode=res_mode,
                mode_source=route.mode_source,
                resident=active_snapshot().get("active_model"),
                catalog_alias=route.catalog_alias,
                fit=route.fit,
            ),
        )
    finally:
        await inference_queue.release(lane=route.lane)


def _native_body_for_mode(body: dict[str, Any], model: str) -> dict[str, Any]:
    out = inject_think_false({**body, "model": model}, model)
    return out


async def run_native_inference(
    *,
    path: str,
    body: dict[str, Any],
    ctx: ForgeContext,
    method: str = "POST",
) -> Response:
    adapter = get_adapter()
    if adapter.kind != "ollama":
        return JSONResponse(
            {
                "error": f"native Ollama API unsupported for runner kind={adapter.kind}",
            },
            status_code=501,
        )

    pseudo_path = "/v1/chat/completions" if path.rstrip("/") == "/api/chat" else "/v1/chat/completions"
    if path.rstrip("/") == "/api/generate":
        pseudo_body = {
            "messages": [{"role": "user", "content": str(body.get("prompt") or "")}],
            "model": body.get("model"),
        }
    else:
        pseudo_body = {
            "messages": body.get("messages") or [],
            "model": body.get("model"),
        }

    ticket = str(uuid.uuid4())
    try:
        task = resolve_task(
            header_task=None,
            body_task=body.get("forge_task") or body.get("task_id"),
            header_mode=ctx.mode,
            body_mode=body.get("forge_mode"),
            path=pseudo_path,
            body=pseudo_body,
        )
        route = await plan_route(task=task, body=pseudo_body, ctx=ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    wait = ctx.wait or DEFAULT_WAIT_BY_MODE.get(task.mode, "bounce")

    model = route.model
    res_mode = task.mode
    if model in QUARANTINED_MODELS:
        raise HTTPException(status_code=400, detail=f"Model quarantined: {model}")

    q = await inference_queue.acquire(
        ticket,
        model=model,
        lane=route.lane,
        hold=(wait == "hold"),
        timeout_sec=float(DEFAULT_HOLD_TIMEOUT_SEC),
    )
    if not q.get("ok"):
        return JSONResponse(
            {
                "error": {
                    "message": "LLM queue busy",
                    "type": "queue_busy",
                    "code": q.get("reason"),
                }
            },
            status_code=503,
            headers={"Retry-After": str(q.get("retry_after_sec", 30))},
        )

    t0 = time.perf_counter()
    try:
        ready, swapped, err = await ensure_model(model, res_mode)
        if not ready:
            raise HTTPException(status_code=503, detail=err or "model unavailable")
        proxied = _native_body_for_mode(body, model)
        status, content, hdrs = await adapter.native_request(
            method,
            path,
            json.dumps(proxied).encode(),
            timeout=float(DEFAULT_HOLD_TIMEOUT_SEC),
        )
        insert_request(
            {
                "ts": time.time(),
                "consumer": ctx.consumer,
                "consumer_class": ctx.consumer_class,
                "mode": res_mode,
                "requested_model": body.get("model"),
                "served_model": model,
                "swap": swapped,
                "total_ms": int((time.perf_counter() - t0) * 1000),
                "http_status": status,
                "ok": status < 400,
                "trace_id": ctx.trace_id,
                "meta": {**_route_evidence(route, task), "path": path},
            }
        )
        return Response(
            content=content,
            status_code=status,
            media_type=hdrs.get("content-type", "application/json"),
            headers={
                "X-Forge-Llm-Mode": res_mode,
                "X-Forge-Task": task.task_id,
                "X-Forge-Served-Model": model,
            },
        )
    finally:
        await inference_queue.release(lane=route.lane)
