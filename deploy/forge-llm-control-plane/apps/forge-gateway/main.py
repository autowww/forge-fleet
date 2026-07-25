"""forge-gateway: Ollama-compatible proxy + OpenAI /v1 control plane + telemetry."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from control_plane.router import router as control_plane_router
from metrics import load_persisted_state, restore_counters_from_disk
from ollama_proxy import proxy_request
from prometheus_client_helpers import metrics_response

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger("forge-gateway")

PROMETHEUS_URL = os.environ.get("PROMETHEUS_INTERNAL_URL", "http://prometheus:9090").rstrip(
    "/"
)
GPU_MODE = os.environ.get("GPU_MODE", "cpu").lower()
FORGE_API_TOKEN = os.environ.get("FORGE_API_TOKEN", "").strip()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
_EFFECTIVE_TOKEN = FORGE_API_TOKEN or LLM_API_KEY
GATEWAY_AUTH_REQUIRED = os.environ.get("GATEWAY_AUTH_REQUIRED", "false").lower() in (
    "1",
    "true",
    "yes",
)

app = FastAPI(title="forge-gateway", version="0.2.0")
app.include_router(control_plane_router)

_runtime_state: dict[str, Any] = {}


@app.on_event("startup")
async def _startup() -> None:
    restore_counters_from_disk()
    _runtime_state.clear()
    _runtime_state.update(load_persisted_state())


def _log(event: str, **fields: Any) -> None:
    payload = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    logger.info(json.dumps(payload, default=str))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path
        if not GATEWAY_AUTH_REQUIRED or not _EFFECTIVE_TOKEN:
            return await call_next(request)
        if path in ("/healthz", "/telemetry/health"):
            return await call_next(request)
        if path == "/metrics":
            return await call_next(request)
        auth = request.headers.get("authorization") or ""
        api_key = request.headers.get("x-api-key") or ""
        token = ""
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ").strip()
        elif api_key:
            token = api_key.strip()
        if not token:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        if token != _EFFECTIVE_TOKEN:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)


app.add_middleware(AuthMiddleware)


def _scalar_first(results: list[dict[str, Any]]) -> float | None:
    if not results:
        return None
    v = results[0].get("value")
    if not v or len(v) < 2:
        return None
    try:
        x = float(v[1])
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


async def build_telemetry_summary() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    mode: str = "nvidia" if GPU_MODE == "nvidia" else "cpu"

    async with httpx.AsyncClient(timeout=20.0) as client:
        async def q(query: str) -> list[dict[str, Any]]:
            r = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}
            )
            r.raise_for_status()
            return r.json().get("data", {}).get("result", [])

        cpu_util = _scalar_first(
            await q(
                '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))'
            )
        )
        load1 = _scalar_first(await q("node_load1"))
        mem_total = _scalar_first(await q("node_memory_MemTotal_bytes"))
        mem_avail = _scalar_first(await q("node_memory_MemAvailable_bytes"))
        ram_used = 0.0
        if mem_total is not None and mem_avail is not None:
            ram_used = max(0.0, mem_total - mem_avail)

        disk_size = _scalar_first(
            await q('max(node_filesystem_size_bytes{mountpoint="/rootfs"})')
        )
        if disk_size is None:
            disk_size = _scalar_first(
                await q('max(node_filesystem_size_bytes{mountpoint="/"})')
            )
        disk_free = _scalar_first(
            await q('max(node_filesystem_avail_bytes{mountpoint="/rootfs"})')
        )
        if disk_free is None:
            disk_free = _scalar_first(
                await q('max(node_filesystem_avail_bytes{mountpoint="/"})')
            )
        disk_used = 0.0
        if disk_size is not None and disk_free is not None:
            disk_used = max(0.0, disk_size - disk_free)

        net_rx = _scalar_first(
            await q('sum(node_network_receive_bytes_total{device!~"lo.*"})')
        )
        net_tx = _scalar_first(
            await q('sum(node_network_transmit_bytes_total{device!~"lo.*"})')
        )

        cpu_temp = _scalar_first(
            await q("max(node_hwmon_temp_celsius)")
        )
        if cpu_temp is None:
            cpu_temp = _scalar_first(await q("max(node_thermal_zone_temp)"))

        gpu_util = _scalar_first(await q("DCGM_FI_DEV_GPU_UTIL"))
        gpu_temp = _scalar_first(await q("DCGM_FI_DEV_GPU_TEMP"))
        vram_used = _scalar_first(await q("DCGM_FI_DEV_FB_USED"))
        vram_free = _scalar_first(await q("DCGM_FI_DEV_FB_FREE"))
        vram_total = None
        if vram_used is not None and vram_free is not None:
            vram_total = vram_used + vram_free

        async def container_block(svc: str) -> dict[str, Any]:
            mem = _scalar_first(
                await q(
                    f'sum(container_memory_usage_bytes{{container_label_com_docker_compose_service="{svc}"}})'
                )
            )
            if mem is None:
                mem = _scalar_first(
                    await q(
                        f'sum(container_memory_usage_bytes{{name=~".*{svc}.*"}})'
                    )
                )
            return {"memory_usage_bytes": mem}

        containers = {
            "forge-gateway": await container_block("forge-gateway"),
            "ollama": await container_block("ollama"),
            "comfyui": await container_block("comfyui"),
            "prometheus": await container_block("prometheus"),
        }

        req_total = _scalar_first(await q("sum(forge_ollama_requests_total)"))
        tin_total = _scalar_first(await q("sum(forge_ollama_tokens_in_total)"))
        tout_total = _scalar_first(await q("sum(forge_ollama_tokens_out_total)"))

        per_model: dict[str, Any] = {}
        pr = await q("sum by (model) (forge_ollama_tokens_in_total)")
        for row in pr:
            m = (row.get("metric") or {}).get("model") or "_unknown"
            v = row.get("value")
            tin = float(v[1]) if v and len(v) > 1 else 0.0
            entry = per_model.setdefault(
                str(m), {"tokens_in": 0.0, "tokens_out": 0.0}
            )
            entry["tokens_in"] = tin
        pr2 = await q("sum by (model) (forge_ollama_tokens_out_total)")
        for row in pr2:
            m = (row.get("metric") or {}).get("model") or "_unknown"
            v = row.get("value")
            tout = float(v[1]) if v and len(v) > 1 else 0.0
            entry = per_model.setdefault(
                str(m), {"tokens_in": 0.0, "tokens_out": 0.0}
            )
            entry["tokens_out"] = tout

    if mode != "nvidia":
        gpu_block = {
            "enabled": False,
            "name": None,
            "utilization_pct": None,
            "temperature_c": None,
            "vram_used_bytes": None,
            "vram_total_bytes": None,
        }
    else:
        gpu_block = {
            "enabled": True,
            "name": None,
            "utilization_pct": gpu_util,
            "temperature_c": gpu_temp,
            "vram_used_bytes": int(vram_used) if vram_used is not None else None,
            "vram_total_bytes": int(vram_total) if vram_total is not None else None,
        }

    return {
        "timestamp": ts,
        "mode": mode,
        "host": {
            "cpu_utilization_pct": round(cpu_util, 3) if cpu_util is not None else 0,
            "cpu_load_1m": round(load1, 3) if load1 is not None else 0,
            "cpu_temp_c": cpu_temp,
            "ram_used_bytes": int(ram_used),
            "ram_total_bytes": int(mem_total or 0),
            "disk_used_bytes": int(disk_used),
            "disk_free_bytes": int(disk_free or 0),
            "disk_total_bytes": int(disk_size or 0),
            "network_rx_bytes": int(net_rx or 0),
            "network_tx_bytes": int(net_tx or 0),
        },
        "gpu": gpu_block,
        "containers": containers,
        "ollama": {
            "requests_total": int(req_total or 0),
            "tokens_in_total": int(tin_total or 0),
            "tokens_out_total": int(tout_total or 0),
            "per_model": per_model,
        },
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/telemetry/health")
async def telemetry_health() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{PROMETHEUS_URL}/-/healthy")
        ok = r.status_code == 200
        return {
            "status": "ok" if ok else "degraded",
            "prometheus": "reachable" if ok else "unreachable",
        }
    except httpx.RequestError:
        return {"status": "degraded", "prometheus": "unreachable"}


@app.get("/telemetry/summary")
async def telemetry_summary() -> dict[str, Any]:
    try:
        return await build_telemetry_summary()
    except httpx.HTTPError as e:
        _log("telemetry_summary_error", error=str(e))
        raise HTTPException(status_code=503, detail="Telemetry unavailable") from e


@app.get("/telemetry/raw")
async def telemetry_raw() -> dict[str, Any]:
    queries = {
        "cpu_util": '100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))',
        "node_load1": "node_load1",
        "mem_total": "node_memory_MemTotal_bytes",
        "forge_requests": "forge_ollama_requests_total",
    }
    if GPU_MODE == "nvidia":
        queries["gpu_util"] = "DCGM_FI_DEV_GPU_UTIL"
    out: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for name, query in queries.items():
            r = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}
            )
            r.raise_for_status()
            out[name] = r.json()
    return out


@app.get("/metrics")
async def prom_metrics() -> Response:
    body, ctype = metrics_response()
    return Response(content=body, media_type=ctype)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
async def api_proxy(path: str, request: Request) -> Response:
    _log("proxy", path=f"/api/{path}", method=request.method)
    return await proxy_request(request, f"/api/{path}", _runtime_state)


@app.middleware("http")
async def log_requests(request: Request, call_next):  # type: ignore[override]
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
        dt = (time.perf_counter() - t0) * 1000
        _log(
            "http",
            method=request.method,
            path=request.url.path,
            status=getattr(response, "status_code", 0),
            ms=round(dt, 2),
        )
        return response
    except Exception:
        dt = (time.perf_counter() - t0) * 1000
        _log("http_error", method=request.method, path=request.url.path, ms=round(dt, 2))
        raise
