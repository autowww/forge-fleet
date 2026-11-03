"""Async reverse proxy to Ollama with streaming support and token accounting."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncIterator

import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from metrics import REQUEST_LATENCY, record_request

logger = logging.getLogger("forge-gateway.ollama")

OLLAMA_BASE = os.environ.get("OLLAMA_INTERNAL_URL", "http://ollama:11434").rstrip("/")


def _needs_think_false(model: str) -> bool:
    m = model.lower()
    return any(p in m for p in ("qwen3", "qwen2.5", "deepseek-r1"))


def _extract_counts(payload: dict[str, Any]) -> tuple[str | None, int, int]:
    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        model = str(model)
    tin = int(payload.get("prompt_eval_count") or 0)
    tout = int(payload.get("eval_count") or 0)
    return (model if isinstance(model, str) else None), tin, tout


def _endpoint_label(path: str) -> str:
    if path.startswith("/api/chat"):
        return "/api/chat"
    if path.startswith("/api/generate"):
        return "/api/generate"
    return "/api"


async def proxy_request(
    request: Request,
    path: str,
    state: dict[str, Any],
) -> Response:
    """Proxy non-streaming and streaming requests to Ollama."""
    url = f"{OLLAMA_BASE}{path}"
    if request.query_params:
        url = f"{url}?{request.query_params}"

    body = await request.body()
    ep = _endpoint_label(path)

    if body and path.startswith("/api/"):
        try:
            j = json.loads(body)
            if isinstance(j, dict):
                model = str(j.get("model") or "")
                if model and _needs_think_false(model) and "think" not in j:
                    j["think"] = False
                    body = json.dumps(j).encode()
        except (json.JSONDecodeError, TypeError):
            pass

    stream = False
    if body:
        try:
            j = json.loads(body)
            stream = bool(j.get("stream"))
        except (json.JSONDecodeError, TypeError):
            stream = False

    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length", "connection"}
    }

    timeout = httpx.Timeout(600.0, connect=30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if stream:
            return await _proxy_stream(
                client, request.method, url, headers, body, ep, state
            )

        t0 = time.perf_counter()
        try:
            r = await client.request(
                request.method,
                url,
                headers=headers,
                content=body,
            )
        except httpx.RequestError as e:
            logger.exception("ollama upstream error: %s", e)
            return Response(status_code=502, content=b"Bad gateway: Ollama unreachable")
        dt = time.perf_counter() - t0
        REQUEST_LATENCY.labels(endpoint=ep).observe(dt)

        content = r.content
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                payload = json.loads(content)
                if isinstance(payload, dict) and payload.get("done", True):
                    model, tin, tout = _extract_counts(payload)
                    record_request(
                        endpoint=ep, model=model, tokens_in=tin, tokens_out=tout, state=state
                    )
            except json.JSONDecodeError:
                pass

        return Response(
            content=content,
            status_code=r.status_code,
            headers={
                k: v
                for k, v in r.headers.items()
                if k.lower() not in {"transfer-encoding", "connection", "content-length"}
            },
            media_type=r.headers.get("content-type"),
        )


async def _proxy_stream(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    ep: str,
    state: dict[str, Any],
) -> StreamingResponse:
    t0 = time.perf_counter()
    buf = b""

    async def gen() -> AsyncIterator[bytes]:
        nonlocal buf
        last_done: dict[str, Any] | None = None
        try:
            async with client.stream(method, url, headers=headers, content=body) as r:
                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError:
                    err = await r.aread()
                    yield err
                    return
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line.decode("utf-8", errors="replace"))
                            if isinstance(obj, dict) and obj.get("done"):
                                last_done = obj
                        except json.JSONDecodeError:
                            continue
                    yield chunk
        finally:
            dt = time.perf_counter() - t0
            REQUEST_LATENCY.labels(endpoint=ep).observe(dt)
            if last_done:
                model, tin, tout = _extract_counts(last_done)
                record_request(
                    endpoint=ep, model=model, tokens_in=tin, tokens_out=tout, state=state
                )

    return StreamingResponse(gen(), media_type="application/x-ndjson")
