"""OpenAI /v1 surface and LLM analytics routes."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from control_plane.cli_lane import is_cli_model, openai_chat_via_cli
from control_plane.interception import adapter_openai, fingerprint_body, inject_think_false, run_openai_inference
from control_plane.catalog_select import enabled_pins, pinned_openai_model_objects
from control_plane.config import (
    DEFAULT_HOLD_TIMEOUT_SEC,
    QUARANTINED_MODELS,
)
from control_plane.context import ForgeContext
from control_plane.external_lane import openai_chat_via_openwebui
from control_plane.finops import suggestions
from control_plane.inventory import build_catalog_inventory
from control_plane.modes import (
    DEFAULT_WAIT_BY_MODE,
    ModeId,
    needs_think_false,
    normalize_mode,
)
from control_plane.queue_manager import inference_queue
from control_plane.route_select import header_task_from_request, plan_route
from control_plane.slot_manager import active_snapshot, ensure_model
from control_plane.task_resolve import resolve_task
from control_plane.store import (
    get_job,
    insert_feedback,
    insert_job,
    insert_request,
    insert_telemetry_event,
    insert_telemetry_events,
    list_requests,
    list_telemetry_events,
    stats_since,
    update_job,
)
from control_plane.telemetry_analytics import telemetry_summary
from control_plane.telemetry_schema import SCHEMA_VERSION, validate_event
from runners.factory import get_adapter
from runners.loader import config_hash, load_runner_config
from control_plane.webhooks import deliver_webhook

router = APIRouter()


async def _run_chat_job(
    job_id: str,
    body: dict[str, Any],
    ctx: ForgeContext,
    resolution_mode: ModeId,
    model: str,
    *,
    lane: str = "local",
    task_id: str = "chat",
) -> None:
    update_job(job_id, status="running")
    t0 = time.perf_counter()
    swapped = False
    try:
        if lane == "external":
            proxied = {**body, "model": model}
            status, content, hdrs = await openai_chat_via_openwebui(model=model, body=proxied)
        else:
            ready, swapped, err = await ensure_model(model, resolution_mode)
            if not ready:
                update_job(job_id, status="failed", error=err or "model_unavailable")
                return
            proxied = inject_think_false({**body, "model": model}, model)
            status, content, hdrs = await adapter_openai(
                "POST", "/v1/chat/completions", json.dumps(proxied).encode()
            )
        data = json.loads(content) if hdrs.get("content-type", "").startswith("application/json") else {}
        if status >= 400:
            update_job(job_id, status="failed", error=content.decode()[:500], completed_ts=time.time())
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
                "status": "completed" if status < 400 else "failed",
                "mode": resolution_mode,
                "model": model,
                "response": data if status < 400 else None,
                "error": None if status < 400 else content.decode()[:500],
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
                "http_status": status,
                "ok": status < 400,
                "trace_id": ctx.trace_id,
                "prompt_fingerprint": fingerprint_body(body),
                "meta": {"async": True, "job_id": job_id, "lane": lane, "task": task_id},
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
    try:
        task = resolve_task(
            header_task=header_task_from_request(dict(request.headers)),
            body_task=raw.get("forge_task") or raw.get("task_id") or body.get("forge_task") or body.get("task_id"),
            header_mode=ctx.mode,
            body_mode=raw.get("forge_mode") or body.get("forge_mode"),
            path=path,
            body=body,
        )
        route = await plan_route(task=task, body=body, ctx=ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "mode": task.mode,
        "model": route.model,
        "source": task.source,
        "task_id": task.task_id,
        "lane": route.lane,
        "catalog_alias": route.catalog_alias,
        "fit": route.fit,
        "mode_source": route.mode_source,
    }


@router.get("/v1/llm/active")
async def llm_active() -> dict[str, Any]:
    depth = await inference_queue.depth()
    snap = active_snapshot()
    snap["queue_depth"] = depth
    return snap


@router.get("/v1/llm/runner")
async def llm_runner() -> dict[str, Any]:
    cfg = load_runner_config()
    adapter = get_adapter(cfg)
    health = await adapter.health()
    snap = active_snapshot()
    snap["queue_depth"] = await inference_queue.depth()
    return {
        "kind": cfg.kind,
        "bind": cfg.bind,
        "config_hash": config_hash(cfg),
        "exclusive_slot": cfg.exclusive_slot,
        "source_path": cfg.source_path,
        "health": health,
        "active": snap,
    }


@router.get("/v1/llm/catalog")
async def llm_catalog() -> dict[str, Any]:
    """Pins, VRAM tier, catalog task fits, and runner install state for Fleet operators."""
    return await build_catalog_inventory()


@router.get("/v1/llm/stats")
async def llm_stats(hours: float = 1.0) -> dict[str, Any]:
    since = time.time() - hours * 3600
    return {
        "window_hours": hours,
        "rollup": stats_since(since),
        "active": active_snapshot(),
        "queue_depth": await inference_queue.depth(),
    }


@router.get("/v1/llm/telemetry/summary")
async def llm_telemetry_summary(hours: float = 24.0) -> dict[str, Any]:
    """Throughput, tokens, models, classifiers, and squid shim savings rollups."""
    since = time.time() - hours * 3600
    base = telemetry_summary(since, hours)
    base["active"] = active_snapshot()
    base["queue_depth"] = await inference_queue.depth()
    return base


@router.get("/v1/llm/telemetry/events")
async def llm_telemetry_events_list(
    hours: float = 24.0,
    kind: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    since = time.time() - hours * 3600
    events = list_telemetry_events(since, kind=kind, limit=min(limit, 500))
    return {"schema_version": SCHEMA_VERSION, "events": events}


@router.post("/v1/llm/telemetry/events")
async def llm_telemetry_events_ingest(request: Request) -> dict[str, Any]:
    """Ingest shim / classifier / NLP telemetry (forge-squid and other clients)."""
    raw = await request.json()
    ctx = ForgeContext.from_headers(dict(request.headers))
    rows: list[dict[str, Any]] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and isinstance(raw.get("events"), list):
        items = raw["events"]
    elif isinstance(raw, dict):
        items = [raw]
    else:
        raise HTTPException(status_code=400, detail="Expected object or events array")
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each event must be an object")
        ok, err = validate_event(item)
        if not ok:
            raise HTTPException(status_code=400, detail=err)
        payload = {
            "schema_version": SCHEMA_VERSION,
            **{k: v for k, v in item.items() if k not in ("ts", "trace_id", "consumer")},
        }
        rows.append(
            {
                "ts": float(item.get("ts") or time.time()),
                "trace_id": item.get("trace_id") or ctx.trace_id,
                "consumer": item.get("consumer") or ctx.consumer,
                "source": item["source"],
                "kind": item["kind"],
                "payload": payload,
            }
        )
    if len(rows) == 1:
        eid = insert_telemetry_event(rows[0])
        return {"status": "ok", "ids": [eid], "schema_version": SCHEMA_VERSION}
    ids = insert_telemetry_events(rows)
    return {"status": "ok", "ids": ids, "schema_version": SCHEMA_VERSION}


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
    status, content, hdrs = await adapter_openai("GET", "/v1/models", b"")
    if status >= 400:
        raise HTTPException(status_code=status, detail=content.decode()[:500])
    data = json.loads(content)
    if os.environ.get("FORGE_LLM_EXPOSE_PINNED_MODELS_ONLY", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        allowed: set[str] = set()
        allowed = {p[0] for p in enabled_pins()}
        models = data.get("data") or []
        if allowed and isinstance(models, list):
            filtered = [m for m in models if isinstance(m, dict) and m.get("id") in allowed]
            data["data"] = pinned_openai_model_objects(filtered, include_synthetic=True)
        elif allowed:
            data["data"] = pinned_openai_model_objects([], include_synthetic=True)
    return data


@router.post("/v1/embeddings")
async def openai_embeddings(request: Request) -> Response:
    body_bytes = await request.body()
    ctx = ForgeContext.from_headers(dict(request.headers))
    try:
        body = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    return await run_openai_inference(
        path="/v1/embeddings",
        body=body,
        ctx=ctx,
        request_headers=dict(request.headers),
    )


@router.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    body_bytes = await request.body()
    hdrs = dict(request.headers)
    ctx = ForgeContext.from_headers(hdrs)
    try:
        body = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    requested = body.get("model")
    if isinstance(requested, str) and is_cli_model(requested):
        to = float(body.get("timeout") or DEFAULT_HOLD_TIMEOUT_SEC)
        status, content, cli_hdrs = await openai_chat_via_cli(
            model=requested, body=body, timeout=to
        )
        media = cli_hdrs.get("content-type", "application/json")
        return Response(content=content, status_code=status, media_type=media)

    try:
        task = resolve_task(
            header_task=header_task_from_request(hdrs),
            body_task=body.get("forge_task") or body.get("task_id"),
            header_mode=ctx.mode,
            body_mode=body.get("forge_mode"),
            path="/v1/chat/completions",
            body=body,
        )
        route = await plan_route(task=task, body=body, ctx=ctx)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    model = route.model
    res_mode = task.mode
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
                "mode": res_mode,
                "model": model,
                "webhook_url": ctx.webhook_url,
                "webhook_secret": ctx.webhook_secret,
                "request": body,
            }
        )
        background_tasks.add_task(
            _run_chat_job,
            job_id,
            body,
            ctx,
            res_mode,
            model,
            lane=route.lane,
            task_id=task.task_id,
        )
        return JSONResponse(
            {"job_id": job_id, "status": "queued"},
            status_code=202,
            headers={"X-Forge-Job-Id": job_id},
        )

    return await run_openai_inference(
        path="/v1/chat/completions",
        body=body,
        ctx=ctx,
        timeout=float(body.get("timeout") or DEFAULT_HOLD_TIMEOUT_SEC),
        request_headers=hdrs,
    )
