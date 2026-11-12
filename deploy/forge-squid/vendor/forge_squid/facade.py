"""Forge Squid — OpenAI-compatible comprehension shim (forge-squid models).

Uses forge-dcs ingest + compile, then upstream LLM via Open WebUI or forge-llm gateway.
"""
from __future__ import annotations

import asyncio
import contextlib
import contextvars
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import Draft202012Validator

from . import attach, branding, cursor_backend, edgar, env_keys, graph, live, squid_catalog, zipingest
from .dce.structured_turn import (
    contract_kind,
    contract_note,
    is_structured_contract,
    json_instruction,
    present_structured,
    relax_answer_shaping,
    reset_contract_note_override,
    set_contract_note_override,
)
from .chat_lane import (
    attached_state_reply,
    capabilities_reply,
    comprehend,
    conversation,
    detached_follow_up_reply,
    flatten_content,
    footer,
    identity_reply,
    previous_answer_reply,
    previous_turn_note,
    refusal_text,
    scrub_self_claim,
    system_prompt,
    trace_reading,
    visible_prefix,
)
from .chat_artifacts import (
    chat_continue_on_length,
    chat_prose_only,
    chat_stream_graph,
    reset_chat_experiment,
    set_chat_experiment,
)
from .prose_turn import (
    ProseProfile,
    assemble_prose,
    enumerate_retry_user_message,
    gate as prose_gate,
    profile_instruction,
    prose_profile,
)
from . import execution_graph
from .chat_plan import (
    bootstrap_graph,
    chat_plan_enabled,
    compile_plan,
    emit_plan_band,
    execute_chat_plan,
)
from .dce import session as dce_session
from .dce import shadow as dce_shadow

log = logging.getLogger("forge_squid")
if not logging.getLogger().handlers:  # uvicorn configures only its own loggers; make node progress visible
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DEFAULT_SQUID_ID = squid_catalog.default_squid_id()
SOURCE_FILE_ID = "forge-squid-note"
_client_model: contextvars.ContextVar[str] = contextvars.ContextVar("client_model", default=DEFAULT_SQUID_ID)
_upstream_model: contextvars.ContextVar[str | None] = contextvars.ContextVar("upstream_model", default=None)
MAX_BODY_BYTES = 8 * 1024 * 1024  # Open WebUI prepends attached-file content to the last user message
TEN_K_MARK = re.compile(r"\bFORM\s+10-K\b|\bANNUAL REPORT PURSUANT TO SECTION 13 OR 15\(d\)", re.I)
SOURCE_PATTERN = re.compile(
    r"\AExtract project and deadline from this note:\r?\n"
    r"SOURCE:\r?\nProject: ([^\r\n]{1,64})\r?\n"
    r"Deadline: (\d{4}-\d{2}-\d{2})\r?\nEND_SOURCE\s*\Z"
)
MODEL_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["facts"],
    "properties": {
        "facts": {
            "type": "object",
            "additionalProperties": False,
            "required": ["project", "deadline"],
            "properties": {
                "project": {"type": "string", "minLength": 1, "maxLength": 64},
                "deadline": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
            },
        }
    },
}
OUTPUT_VALIDATOR = Draft202012Validator(MODEL_OUTPUT_SCHEMA)
DEFAULT_BACKEND = "qwen3.5:2b-q4_K_M"


def _require_http_url(name: str, value: str) -> str:
    if not value:
        return value
    p = urlparse(value)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise POCError(503, "NOT_CONFIGURED", f"{name} must be an http(s) URL")
    return value.rstrip("/")


@dataclass(frozen=True)
class Config:
    enabled: bool
    incoming_key: str
    dcs_url: str
    dcs_key: str
    backend_model: str = DEFAULT_BACKEND
    default_squid_id: str = squid_catalog.DEFAULT_SQUID_ID
    llm_url: str = ""
    llm_key: str = ""
    backend_kind: str = "openwebui"
    cursor_api_key: str = ""
    openwebui_base_url: str = ""
    openwebui_api_key: str = ""
    max_attempts: int = 2
    # graph executor knobs
    edgar_user_agent: str = branding.DEFAULT_EDGAR_USER_AGENT
    cache_dir: Path | None = None
    max_source_bytes: int = 2 * 1024 * 1024
    window_chars: int = 2000
    max_windows: int = 240
    top_n: int = 80
    live_snapshot_s: float = 20.0  # min seconds between live-graph artifact snapshots in the 10-K lane
    llm_timeout: float = 120.0
    zip_limits: zipingest.Limits = zipingest.Limits()
    # DCE-04: off (default, legacy only) | shadow (DCE planned beside legacy, trace only) | on (DCE answers tested attachment ops)
    dce_mode: str = "off"
    dce_plan_ms: float = 3000.0   # measured on the 68-file G1R3A bundle (lab shim, warm index): median 0.45 s, compare questions 1.2–1.5 s — 1.5 s lost K20 by 6 ms (after11)
    dce_max_model_calls: int = 3
    dce_concurrency: int = 2

    @classmethod
    def from_env(cls) -> "Config":
        dcs = _require_http_url("DCS_BASE_URL", os.environ.get("DCS_BASE_URL", "http://127.0.0.1:9793"))
        cache = env_keys.squid_env("CACHE_DIR")
        d = zipingest.Limits()
        limits = zipingest.Limits(
            max_archive_bytes=int(os.environ.get("FORGE_SQUID_ZIP_MAX_ARCHIVE_MB", d.max_archive_bytes // 1048576)) * 1048576,
            max_total_uncompressed=int(os.environ.get("FORGE_SQUID_ZIP_MAX_TOTAL_MB", d.max_total_uncompressed // 1048576)) * 1048576,
            max_file_bytes=int(os.environ.get("FORGE_SQUID_ZIP_MAX_FILE_MB", d.max_file_bytes // 1048576)) * 1048576,
            max_files=int(os.environ.get("FORGE_SQUID_ZIP_MAX_FILES", d.max_files)),
            max_path_len=int(os.environ.get("FORGE_SQUID_ZIP_MAX_PATH", d.max_path_len)),
            max_ratio=int(os.environ.get("FORGE_SQUID_ZIP_MAX_RATIO", d.max_ratio)),
        )
        default_squid = squid_catalog.default_squid_id()
        return cls(
            zip_limits=limits,
            enabled=env_keys.squid_env("ENABLE_LIVE") == "1",
            incoming_key=env_keys.squid_env("API_KEY"),
            dcs_url=dcs,
            dcs_key=os.environ.get("DCS_BEARER_TOKEN", os.environ.get("DCS_API_KEY", "")),
            llm_url=_require_http_url(
                "FORGE_SQUID_LLM_BASE_URL",
                env_keys.squid_env("LLM_BASE_URL", default=""),
            ),
            llm_key=env_keys.squid_env("LLM_API_KEY"),
            backend_model=DEFAULT_BACKEND,
            backend_kind="gateway" if env_keys.squid_env("LLM_BASE_URL") else "openwebui",
            cursor_api_key=env_keys.squid_env("CURSOR_API_KEY", default=os.environ.get("CURSOR_API_KEY", "")),
            default_squid_id=default_squid,
            openwebui_base_url=squid_catalog.openwebui_base_url(),
            openwebui_api_key=squid_catalog.openwebui_api_key(),
            edgar_user_agent=env_keys.squid_env("EDGAR_USER_AGENT", default=cls.edgar_user_agent),
            cache_dir=Path(cache) if cache else None,
            window_chars=env_keys.squid_env_int("WINDOW_CHARS", cls.window_chars),
            max_windows=env_keys.squid_env_int("MAX_WINDOWS", cls.max_windows),
            top_n=env_keys.squid_env_int("TOP_N", cls.top_n),
            live_snapshot_s=env_keys.squid_env_float("LIVE_SNAPSHOT_S", cls.live_snapshot_s),
            llm_timeout=env_keys.squid_env_float("LLM_TIMEOUT", cls.llm_timeout),
            dce_mode=dce_shadow.normalize_mode(env_keys.squid_env("DCE_MODE", default="off")),
            dce_plan_ms=env_keys.squid_env_float("DCE_PLAN_MS", cls.dce_plan_ms),
            dce_max_model_calls=env_keys.squid_env_int("DCE_MAX_MODEL_CALLS", cls.dce_max_model_calls),
            dce_concurrency=max(1, env_keys.squid_env_int("DCE_CONCURRENCY", cls.dce_concurrency)),
        )


def _last_user_text(messages: Any) -> str | None:
    """Open WebUI sends full history; the PoC acts on the last plain-text user message only."""
    if not isinstance(messages, list) or not messages:
        return None
    for m in reversed(messages):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, list):  # OpenAI content-parts form
            c = "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        return c if isinstance(c, str) and c.strip() else None
    return None


class POCError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def err(exc: POCError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"message": exc.message, "type": "forge_poc_error", "param": None, "code": exc.code}},
    )


def parse_fixture(prompt: str) -> tuple[dict[str, str], bytes]:
    match = SOURCE_PATTERN.fullmatch(prompt)
    if not match:
        raise POCError(422, "UNSUPPORTED_INPUT", "Text is not the documented SOURCE/END_SOURCE fixture.")
    project, deadline = match.groups()
    if not project.strip():
        raise POCError(422, "INVALID_SOURCE", "Empty project")
    try:
        date.fromisoformat(deadline)
    except ValueError as ex:
        raise POCError(422, "INVALID_SOURCE", "Deadline is not a valid ISO date") from ex
    facts = {"project": project, "deadline": deadline}
    source = f"Project: {project}\nDeadline: {deadline}\n".encode("utf-8")
    return facts, source


def compile_request_from_ref(file_id: str, version: str, content_hash: str) -> dict[str, Any]:
    return {
        "prompt": "Extract the fields project and deadline from the attached document.",
        "mode": "STRICT",
        "file_refs": [{"file_id": file_id, "version": version, "content_hash": content_hash}],
        "requested_fields": ["project", "deadline"],
        "max_context_tokens_per_task": 512,
    }


def validate_plan(plan: Any, file_ref: dict[str, str]) -> None:
    if not isinstance(plan, dict) or plan.get("schema_version") != "planir.v0.1" or plan.get("determinism_class") != "STRICT":
        raise POCError(502, "INVALID_DCS_PLAN", "DCS returned an unexpected plan contract")
    if plan.get("source_versions") != [file_ref] or plan.get("coverage", {}).get("status") != "COMPLETE":
        raise POCError(502, "INVALID_DCS_PLAN", "DCS source or coverage does not match the request")
    nodes = {n.get("node_id"): n for n in plan.get("tasks", []) if isinstance(n, dict)}
    frag = f"{file_ref['file_id']}@{file_ref['version']}#root"
    scope = f"{file_ref['file_id']}@{file_ref['content_hash']}"
    if (
        len(plan.get("tasks", [])) != 2
        or set(nodes) != {"extract_main", "validate_main"}
        or nodes["extract_main"].get("fragment_refs") != [frag]
        or nodes["extract_main"].get("source_scope") != [scope]
        or nodes["extract_main"].get("depends_on") != []
        or nodes["validate_main"].get("routing_class") != "zero_model"
        or nodes["validate_main"].get("depends_on") != ["extract_main"]
        or plan.get("edges") != [{"from": "extract_main", "to": "validate_main", "binding_ref": "extracted_facts"}]
    ):
        raise POCError(502, "INVALID_DCS_PLAN", "DCS graph, scope or bindings differ from pinned fixture")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(plan.get("plan_hash", ""))):
        raise POCError(502, "INVALID_DCS_PLAN", "Invalid DCS plan hash format")


def validate_output(text: str, expected: dict[str, str]) -> dict[str, str]:
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        raise POCError(502, "OUTPUT_NOT_JSON", "Backend response is not valid JSON")
    if list(OUTPUT_VALIDATOR.iter_errors(obj)):
        raise POCError(502, "OUTPUT_SCHEMA_INVALID", "Backend response violates required facts schema")
    if obj["facts"] != expected:
        raise POCError(502, "SOURCE_FIDELITY_FAILED", "Backend output does not match authorized source")
    return obj["facts"]


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _response_model() -> str:
    return _client_model.get()


def _effective_backend_model(cfg: Config) -> str:
    upstream = _upstream_model.get()
    return upstream if upstream else cfg.backend_model


def _text_response(body: dict[str, Any], run_id: str, content: str, headers: dict[str, str]):
    """Single-shot OpenAI chat response (JSON or one-chunk SSE) for lanes whose result is already final."""
    created = int(time.time())
    response_id = "chatcmpl-" + run_id
    alias = _response_model()
    if body.get("stream"):

        def chunk(delta: dict[str, str], finish: str | None = None) -> str:
            frame = {"id": response_id, "object": "chat.completion.chunk", "created": created, "model": alias,
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

        async def generate():
            yield chunk({"role": "assistant"})
            yield chunk({"content": content})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)
    return JSONResponse(
        content={"id": response_id, "object": "chat.completion", "created": created, "model": alias,
                 "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]},
        headers=headers,
    )


def _backend_matches(served: str, expected: str) -> bool:
    if served == expected:
        return True
    if served.endswith(expected) or served.removeprefix("forge-llm.") == expected:
        return True
    return False


def _backend_label(cfg: Config) -> str:
    up = _upstream_model.get() or cfg.backend_model
    return f"{up} (Open WebUI upstream)"


def create_app(config: Config | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    cfg = config or Config.from_env()
    app = FastAPI(title="forge-squid OpenAI API PoC", docs_url=None, redoc_url=None)
    traces: dict[str, dict[str, Any]] = {}
    run_sem = asyncio.Semaphore(1)
    dce_sem = asyncio.Semaphore(cfg.dce_concurrency)
    dce_budget = dce_shadow.Budget(plan_ms=cfg.dce_plan_ms, max_model_calls=cfg.dce_max_model_calls, max_attempts=cfg.max_attempts)
    dce_store = dce_session.SessionStore()   # per-conversation last two turns, in memory only (decision 5)
    catalog_cache: squid_catalog.SquidCatalog | None = squid_catalog.load_disk_cache()
    catalog_at: float = time.monotonic() if catalog_cache is not None else 0.0
    catalog_lock = asyncio.Lock()

    async def refresh_catalog(client: httpx.AsyncClient) -> squid_catalog.SquidCatalog:
        nonlocal catalog_cache, catalog_at
        if not cfg.openwebui_base_url:
            return squid_catalog.SquidCatalog.empty(error="openwebui_base_url_not_configured")
        fetched = await squid_catalog.fetch_catalog(client, cfg.openwebui_base_url, cfg.openwebui_api_key)
        async with catalog_lock:
            if fetched.entries:
                catalog_cache = fetched
                catalog_at = time.monotonic()
            elif catalog_cache is None:
                catalog_cache = fetched
        return catalog_cache or fetched

    async def get_catalog(client: httpx.AsyncClient, *, allow_fetch: bool = True) -> squid_catalog.SquidCatalog:
        nonlocal catalog_cache, catalog_at
        if not cfg.openwebui_base_url:
            return squid_catalog.SquidCatalog.empty(error="openwebui_base_url_not_configured")
        async with catalog_lock:
            if catalog_cache is not None and time.monotonic() - catalog_at < 60.0:
                return catalog_cache
        if not allow_fetch:
            async with catalog_lock:
                return catalog_cache or squid_catalog.SquidCatalog.empty(error="catalog_warming")
        return await refresh_catalog(client)

    async def _catalog_refresh_loop() -> None:
        refresh_s = float(os.environ.get("FORGE_SQUID_CATALOG_REFRESH_S", "90"))
        await asyncio.sleep(5.0)
        while True:
            try:
                async with httpx.AsyncClient(transport=transport, timeout=45.0, follow_redirects=False) as client:
                    await refresh_catalog(client)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(max(30.0, refresh_s))

    @app.on_event("startup")
    async def _squid_catalog_background() -> None:
        asyncio.create_task(_catalog_refresh_loop())

    def resolve_client_model(model: str, catalog: squid_catalog.SquidCatalog) -> tuple[str, str]:
        try:
            return catalog.resolve_client_model(model)
        except ValueError as ex:
            raise POCError(404, "MODEL_NOT_FOUND", "Unknown PoC model") from ex
        except KeyError as ex:
            raise POCError(404, "MODEL_NOT_FOUND", "Unknown forge-squid model") from ex

    @contextlib.asynccontextmanager
    async def request_route(client_model: str, upstream_model: str):
        t_client = _client_model.set(client_model)
        t_upstream = _upstream_model.set(upstream_model)
        try:
            yield
        finally:
            _client_model.reset(t_client)
            _upstream_model.reset(t_upstream)

    async def dce_plan(ings: list[zipingest.Ingest], query: str, run_id: str, record: dict[str, Any]) -> dce_shadow.Plan | None:
        """Bounded deterministic DCE stage (parse → map → DAG → dry-run retrieval). Never raises: failures are recorded
        under record['dce'] and the caller falls back to the legacy lane."""
        t0 = time.monotonic()
        # the plan stage is linear in the indexed lines (one Python pass over the FTS candidates): the 3 s default was
        # measured on a 99 k-line package; a 293 k-line package's compare plan takes ~4 s (live L26 G1R3D, lab after05 /
        # after07 / after08 2026-11-07: PLAN_TIMEOUT at 3 s, then the legacy lane) — the budget scales with the size
        lines = sum(e.lines for i in ings for e in i.included)
        budget_ms = cfg.dce_plan_ms * max(1.0, lines / 100_000.0)
        try:
            async with dce_sem:
                plan = await asyncio.wait_for(asyncio.to_thread(dce_shadow.build_plan, ings, query, run_id, budget=dce_budget),
                                              timeout=max(0.05, budget_ms / 1000.0))
        except asyncio.TimeoutError:
            record["dce"] = {"version": dce_shadow.TRACE_VERSION, "mode": cfg.dce_mode, "status": "PLAN_TIMEOUT",
                             "plan_ms": round((time.monotonic() - t0) * 1000, 1), "budget_ms": round(budget_ms, 1), "indexed_lines": lines, "model_calls_made": 0}
            return None
        except Exception as ex:  # noqa: BLE001 — shadow must never break the user-visible response
            record["dce"] = {"version": dce_shadow.TRACE_VERSION, "mode": cfg.dce_mode, "status": "PLAN_FAILED",
                             "error": f"{type(ex).__name__}: {str(ex)[:160]}", "model_calls_made": 0}
            return None
        record["dce"] = dce_shadow.sanitized_trace(plan, cfg.dce_mode)
        return plan

    def require_access(request: Request) -> None:
        if not cfg.incoming_key:
            raise POCError(503, "NOT_CONFIGURED", "PoC API key not configured")
        header = request.headers.get("authorization", "")
        provided = header[7:] if header.startswith("Bearer ") else ""
        if not hmac.compare_digest(provided, cfg.incoming_key):
            raise POCError(401, "UNAUTHORIZED", "Missing or invalid bearer token")

    def require_live() -> None:
        if not cfg.enabled:
            raise POCError(503, "LIVE_DISABLED", "Live PoC is disabled")
        needed = [cfg.dcs_url, cfg.dcs_key, cfg.incoming_key]
        has_llm = bool(cfg.llm_url and cfg.llm_key)
        has_catalog = bool(cfg.openwebui_base_url)
        if not all(needed) or not (has_llm or has_catalog):
            raise POCError(503, "UPSTREAM_NOT_CONFIGURED", "DCS, forge-llm gateway, or Open WebUI catalog is not configured")

    async def call(client: httpx.AsyncClient, method: str, url: str, key: str, **kw: Any) -> Any:
        try:
            response = await client.request(method, url, headers=_headers(key), **kw)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as ex:
            raise POCError(503, "UPSTREAM_UNAVAILABLE", "Required upstream endpoint failed") from ex

    async def check_backend(client: httpx.AsyncClient) -> dict[str, Any]:
        caps = await call(client, "GET", cfg.dcs_url.rstrip("/") + "/v1/capabilities", cfg.dcs_key)
        if "STRICT" not in caps.get("modes", []) or caps.get("model_calls_in_compile") is not False:
            raise POCError(503, "DCS_STRICT_UNAVAILABLE", "DCS strict compile contract unavailable")
        sources = caps.get("sources") or {}
        if not sources.get("configured"):
            raise POCError(503, "DCS_SOURCES_UNAVAILABLE", "DCS source store is not configured (ingest-first PoC)")
        upstream = _upstream_model.get()
        catalog_trace: dict[str, Any] = (
            {"note": "openwebui upstream", "upstream_model": upstream} if upstream else {"note": "openwebui catalog"}
        )
        return {"capabilities": caps, "catalog_trace": catalog_trace}

    async def complete_backend(client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
        upstream = _upstream_model.get()
        if not upstream:
            raise POCError(503, "UPSTREAM_NOT_CONFIGURED", "Request has no resolved Open WebUI upstream model")
        payload = dict(body)
        payload["model"] = upstream
        if cursor_backend.is_cursor_model(upstream):
            if not (cfg.llm_url and cfg.llm_key):
                raise POCError(503, "UPSTREAM_NOT_CONFIGURED", "Composer is served by the forge-llm gateway CLI lane")
            url = squid_catalog.llm_gateway_completion_url(cfg.llm_url)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {cfg.llm_key}"}
            try:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                answer = response.json()
            except (httpx.HTTPError, ValueError) as ex:
                raise POCError(503, "UPSTREAM_UNAVAILABLE", "forge-llm gateway CLI completion failed") from ex
            if not isinstance(answer, dict):
                raise POCError(502, "INVALID_GATEWAY_RESPONSE", "Gateway CLI response malformed")
            return answer
        # Qwen via Open WebUI may answer only in reasoning_content unless thinking is off.
        payload.setdefault("think", False)
        payload.setdefault("reasoning_effort", "none")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        via = env_keys.first_env("FORGE_SQUID_COMPLETION_BACKEND").strip().lower()
        use_gateway = via != "openwebui" and bool(cfg.llm_url and cfg.llm_key)
        if use_gateway:
            url = squid_catalog.llm_gateway_completion_url(cfg.llm_url)
            headers["Authorization"] = f"Bearer {cfg.llm_key}"
            upstream_label = "forge-llm gateway"
        else:
            if not cfg.openwebui_base_url:
                raise POCError(503, "UPSTREAM_NOT_CONFIGURED", "Open WebUI base URL is not configured")
            if cfg.openwebui_api_key:
                headers["Authorization"] = f"Bearer {cfg.openwebui_api_key}"
            url = squid_catalog.completion_url(cfg.openwebui_base_url)
            upstream_label = "Open WebUI"
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            answer = response.json()
        except (httpx.HTTPError, ValueError) as ex:
            raise POCError(503, "UPSTREAM_UNAVAILABLE", f"{upstream_label} chat completion failed") from ex
        if not isinstance(answer, dict):
            raise POCError(502, "INVALID_GATEWAY_RESPONSE", "Open WebUI response malformed")
        served = str(answer.get("model", ""))
        if squid_catalog.is_shim_upstream_id(served):
            raise POCError(502, "BACKEND_MODEL_MISMATCH", "Open WebUI returned a shim model (loop)")
        if not _backend_matches(served, upstream):
            raise POCError(502, "BACKEND_MODEL_MISMATCH", "Open WebUI returned a different served model")
        return answer

    async def ingest_source(client: httpx.AsyncClient, data: bytes, file_id: str = SOURCE_FILE_ID) -> dict[str, str]:
        url = cfg.dcs_url.rstrip("/") + "/v1/sources"
        try:
            response = await client.post(
                url,
                headers={
                    **_headers(cfg.dcs_key),
                    "X-Dcs-File-Id": file_id,
                    "Content-Type": "text/plain",
                },
                content=data,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as ex:
            raise POCError(503, "UPSTREAM_UNAVAILABLE", "DCS ingest failed") from ex
        return {
            "file_id": body["file_id"],
            "version": body["version"],
            "content_hash": body["content_hash"],
        }

    @app.exception_handler(POCError)
    async def _poc_error(_: Request, exc: POCError) -> JSONResponse:
        return err(exc)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "ok": True,
            "service": branding.SERVICE_NAME,
            "live_enabled": cfg.enabled,
            "dce_mode": cfg.dce_mode,
            "backend_kind": cfg.backend_kind,
            "default_squid_model": cfg.default_squid_id,
            "openwebui_catalog": bool(cfg.openwebui_base_url),
        }

    @app.get("/v1/models")
    async def models(request: Request) -> dict[str, Any]:
        require_access(request)
        require_live()
        # Never call Open WebUI /api/models on this path: OWUI aggregates connections by
        # fetching this endpoint and would deadlock (ReadTimeout → empty catalog).
        async with httpx.AsyncClient(transport=transport, timeout=30.0, follow_redirects=False) as client:
            await check_backend(client)
            catalog = await get_catalog(client, allow_fetch=False)
        rows = [
            {"id": squid_catalog.public_model_id(entry), "object": "model", "created": 0, "owned_by": branding.SERVICE_NAME}
            for entry in catalog.entries
        ]
        return {"object": "list", "data": rows, "squid_catalog": catalog.trace()}

    @app.get("/v1/forge/runs/{run_id}")
    async def run_trace(run_id: str, request: Request) -> dict[str, Any]:
        require_access(request)
        if run_id not in traces:
            raise POCError(404, "RUN_NOT_FOUND", "No such run in this PoC process")
        return dict(traces[run_id])

    async def edgar_source(client: httpx.AsyncClient, ticker: str | None, accession: str | None) -> tuple[str, bytes, dict[str, Any]]:
        assert ticker is not None
        try:
            ref = await edgar.resolve_filing(client, ticker, accession, user_agent=cfg.edgar_user_agent)
            data = await edgar.fetch_filing_text(client, ref, user_agent=cfg.edgar_user_agent, cache_dir=cfg.cache_dir)
        except edgar.EdgarError as ex:
            raise POCError(502, ex.code, ex.message) from ex
        return ref.file_id, data, edgar.filing_meta(ref, data)

    async def graph_run(request: Request, body: dict[str, Any], user_text: str, *, directive: tuple[str | None, str | None] | None = None,
                        source_loader=None, extra_record: dict[str, Any] | None = None):
        """10-K directive -> forge-dcs plan -> windowed atomic Q2 decisions -> deterministic reduce."""
        if directive is None:
            directive = edgar.parse_directive(user_text)
        assert directive is not None
        ticker, accession = directive
        load_source = source_loader or (lambda client: edgar_source(client, ticker, accession))
        run_id = uuid.uuid4().hex
        created = int(time.time())
        response_id = "chatcmpl-" + run_id
        stream = bool(body.get("stream"))

        def chunk(delta: dict[str, str], finish: str | None = None) -> str:
            frame = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": _response_model(),
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

        record: dict[str, Any] = {
            "run_id": run_id,
            "kind": "graph",
            "model_alias": _response_model(),
            "backend_model": cfg.backend_model,
            "raw_prompt_sha256": hashlib.sha256(user_text.encode()).hexdigest(),
            "directive": {"ticker": ticker, "accession": accession},
            "skill": {"id": graph.SKILL_BUNDLE.skill_id, "version": graph.SKILL_BUNDLE.version},
            "status": "RUNNING",
            "stages": ["accepted"],
            "windows": [],
            "result": [],
            **(extra_record or {}),
        }
        if len(traces) >= 100:
            traces.pop(next(iter(traces)))
        traces[run_id] = record

        lg = live.LiveGraph(run_id, "graph")
        lg.add("source", "zero_model", "attached 10-K file" if source_loader else "SEC EDGAR fetch + HTML→paragraph text")
        lg.add("plan", "dcs", "forge-dcs ingest + plan compile (deterministic)")
        lg.add("triage", "zero_model", "signal-lexicon paragraph scoring + windowing; no neural NLP model")
        lg.add("windows", "fixed_model", f"{_backend_label(cfg)}, one atomic call per window")
        lg.add("reduce", "zero_model", "normalize + iXBRL verify + composite score + cluster, top-N")
        record["steps"] = lg.steps()

        async def body_gen():
            """Yields markdown text pieces; raises POCError on run failure (before any text when possible)."""
            async with run_sem:
                async with httpx.AsyncClient(transport=transport, timeout=cfg.llm_timeout, follow_redirects=False) as client:
                    trace_meta = await check_backend(client)
                    record["upstream_catalog"] = trace_meta.get("catalog_trace")
                    lg.start("source")
                    source_file_id, data, source_meta = await load_source(client)
                    if len(data) > cfg.max_source_bytes:
                        raise POCError(413, "SOURCE_TOO_LARGE", "Filing text exceeds DCS source cap")
                    record["source"] = source_meta
                    record["stages"].append("source_resolved")
                    lg.finish("source", "COMMITTED", f"{len(data):,} bytes · {source_meta.get('kind', 'edgar')}")
                    lg.start("plan")
                    file_ref = await ingest_source(client, data, source_file_id)
                    record["source"].update(file_ref)
                    req = {
                        "prompt": "Extract the most impactful statements from the attached document.",
                        "mode": "STRICT",
                        "file_refs": [file_ref],
                        "requested_fields": ["impactful_statements"],
                        "max_context_tokens_per_task": 1024,
                    }
                    plan = await call(client, "POST", cfg.dcs_url.rstrip("/") + "/v1/plans", cfg.dcs_key, json=req)
                    validate_plan(plan, file_ref)
                    record["plan_hash"] = plan["plan_hash"]
                    record["plan_intent"] = plan.get("intent")
                    record["stages"].append("dcs_ingest_compile_pass")
                    lg.finish("plan", "COMMITTED", f"plan {plan['plan_hash'][:19]}")
                    lg.start("triage")
                    frags = await call(
                        client,
                        "GET",
                        f"{cfg.dcs_url.rstrip('/')}/v1/sources/{file_ref['file_id']}/versions/{file_ref['version']}/fragments",
                        cfg.dcs_key,
                    )
                    paragraphs = graph.paragraphs_from_fragments(data, frags.get("fragments", []))
                    counts = graph.triage(paragraphs)
                    windows, threshold = graph.build_windows(paragraphs, window_chars=cfg.window_chars, max_windows=cfg.max_windows)
                    counts["windows"] = len(windows)
                    counts["signal_threshold"] = threshold
                    record["triage"] = counts
                    record["stages"].append("triage_pass")
                    if not windows:
                        raise POCError(422, "NO_MATERIAL_CONTENT", "Deterministic triage kept no paragraphs")
                    lg.finish("triage", "COMMITTED", f"{counts['total']} paragraphs → {counts['kept']} kept → {len(windows)} windows (signal ≥ {threshold})")
                    lg.start("windows", f"0/{len(windows)} windows")
                    lg.progress("windows", 0, len(windows))
                    yield lg.snapshot_html()
                    yield graph.render_markdown_header(run_id, plan["plan_hash"], file_ref, counts, len(windows), threshold)
                    last_snap = time.monotonic()

                    async def llm(msgs: list[dict[str, str]], max_tokens: int) -> tuple[str, str]:
                        answer = await complete_backend(
                            client,
                            {"model": _effective_backend_model(cfg), "messages": msgs, "temperature": 0, "max_tokens": max_tokens, "stream": False},
                        )
                        served = str(answer.get("model", ""))
                        if not _backend_matches(served, _effective_backend_model(cfg)):
                            raise POCError(502, "BACKEND_MODEL_MISMATCH", "Gateway returned a different served model")
                        try:
                            return str(answer["choices"][0]["message"]["content"]), served
                        except (KeyError, IndexError, TypeError) as ex:
                            raise POCError(502, "INVALID_GATEWAY_RESPONSE", "Gateway response malformed") from ex

                    log.info("run %s: %s paragraphs -> %s windows (threshold %s) for %s", run_id, counts["total"], len(windows), threshold, file_ref["file_id"])
                    for w in windows:
                        await graph.run_window(w, llm, max_attempts=cfg.max_attempts)
                        log.info("run %s: %s %s stmts=%d attempts=%d %dms %s", run_id, w.node_id, w.status, len(w.statements), w.attempts, w.latency_ms, w.failure or "")
                        record["windows"].append(
                            {
                                "node_id": w.node_id,
                                "routing_class": "fixed_model",
                                "fragment_ids": w.fragment_ids,
                                "status": w.status,
                                "attempts": w.attempts,
                                "latency_ms": w.latency_ms,
                                "prompt_sha256": w.prompt_sha256,
                                "served_model": w.served_model,
                                "statements": w.statements,
                                "failure": w.failure,
                                "input_preview": w.text[:600],
                                "raw_output": w.raw_output[:600],
                            }
                        )
                        yield graph.render_progress_line(w)
                        done = len(record["windows"])
                        avg = sum(x["latency_ms"] for x in record["windows"]) / done
                        eta = int(avg * (len(windows) - done) / 1000)
                        lg.progress("windows", done, len(windows),
                                    f"{done}/{len(windows)} windows · {sum(1 for x in record['windows'] if x['status'] == 'COMMITTED')} committed · avg {int(avg)} ms · ETA {eta} s")
                        if time.monotonic() - last_snap >= cfg.live_snapshot_s and done < len(windows):
                            last_snap = time.monotonic()
                            yield lg.snapshot_html()
                    committed = [w for w in windows if w.status == "COMMITTED"]
                    lg.finish("windows", "COMMITTED" if committed else "FAILED",
                              f"{len(committed)}/{len(windows)} windows committed, {sum(w.attempts for w in windows)} LLM call(s)")
                    if not committed:
                        record["status"] = "FAILED"
                        raise POCError(502, "OUTPUT_VALIDATION_FAILED", "No window node committed; no result")
                    lg.start("reduce")
                    result = graph.reduce_statements(
                        windows,
                        top_n=cfg.top_n,
                        filing_html=data,
                        skill_bundle=graph.SKILL_BUNDLE,
                    )
                    record["result"] = result
                    record["observations"] = result
                    record["status"] = "COMMITTED"
                    record["stages"] += ["reduce_pass", "atomic_commit"]
                    lg.finish("reduce", "COMMITTED", f"{len(result)} ranked statements")
                    lg.close("COMMITTED")
                    record["steps"] = lg.steps()
                    yield graph.render_result_markdown(result, windows, run_id)
                    yield lg.snapshot_html(final=True)
                    yield graph.render_graph_html(
                        {k: record[k] for k in ("run_id", "status", "plan_hash", "plan_intent", "source", "triage", "windows", "result")}
                    )

        def _fail(ex: POCError) -> POCError:
            record["status"] = "FAILED"
            record["stages"].append("run_failed")
            return POCError(ex.status, ex.code, f"{ex.message} (run {run_id})")

        if not stream:
            parts: list[str] = []
            try:
                async for piece in body_gen():
                    if not live.is_live_snapshot(piece):
                        parts.append(piece)
            except POCError as ex:
                raise _fail(ex) from ex
            content = "".join(parts)
            headers = {"X-Forge-Run-Id": run_id, "X-Forge-Plan-Hash": record.get("plan_hash", ""), "Cache-Control": "no-store"}
            return JSONResponse(
                content={
                    "id": response_id,
                    "object": "chat.completion",
                    "created": created,
                    "model": _response_model(),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                },
                headers=headers,
            )

        gen = body_gen()
        try:
            first = await gen.__anext__()  # surfaces preflight/DCS/EDGAR failures as proper HTTP errors
        except POCError as ex:
            raise _fail(ex) from ex
        except StopAsyncIteration:
            raise _fail(POCError(502, "OUTPUT_VALIDATION_FAILED", "Empty run"))

        async def generate():
            yield chunk({"role": "assistant"})
            yield chunk({"content": first})
            try:
                async for piece in gen:
                    yield chunk({"content": piece})
            except POCError as ex:
                record["status"] = "FAILED"
                record["stages"].append("run_failed")
                lg.close("FAILED")
                yield chunk({"content": f"\n\n**Run failed:** `{ex.code}` — {ex.message}. No result committed.\n"})
                yield chunk({"content": lg.snapshot_html(final=True)})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Forge-Run-Id": run_id, "Cache-Control": "no-store"},
        )

    @app.put("/v1/forge/ingest/process")
    async def ingest_process(request: Request):
        """Open WebUI External Document Loader contract: raw file bytes in, {page_content, metadata} out.

        Deterministic, no inference, nothing persisted here. ZIP -> bounded in-memory extraction + manifest;
        text files pass through; other binaries are rejected explicitly (415) so the uploader sees why.
        """
        require_access(request)
        from urllib.parse import unquote

        raw = await request.body()
        if len(raw) > cfg.zip_limits.max_archive_bytes:
            raise POCError(413, "ZIP_TOO_LARGE", f"Upload exceeds {cfg.zip_limits.max_archive_bytes} bytes")
        filename = unquote(request.headers.get("x-filename", "")) or "upload"
        mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
        owner = request.headers.get("x-openwebui-user-id", "")
        is_zip = raw[:4] in (b"PK\x03\x04", b"PK\x05\x06") or mime in ("application/zip", "application/x-zip-compressed") or filename.lower().endswith(".zip")
        t0 = time.monotonic()
        if is_zip:
            try:
                ing = zipingest.ingest_zip(raw, filename, cfg.zip_limits, html_to_text=edgar.html_to_paragraph_text)
            except zipingest.ZipIngestError as ex:
                log.info("ingest %s user=%s zip rejected %s", filename, owner, ex.code)
                raise POCError(422, ex.code, ex.message) from ex
            content = zipingest.render(ing)
            warmed: dict[str, Any] = {}
            if cfg.dce_mode != "off":
                # Parse structure and build the retrieval index now, while the uploader is already waiting, so the
                # first question's deterministic plan stage is a cache lookup instead of a multi-second cold build
                # that blows its budget and silently sends the question to the legacy lane.
                try:
                    warmed = await asyncio.to_thread(dce_shadow.warm_caches, ing)
                except Exception as ex:  # noqa: BLE001 — warming is an optimisation; ingest must still succeed
                    warmed = {"error": f"{type(ex).__name__}: {str(ex)[:120]}"}
            log.info("ingest %s user=%s archive=%s entries=%d included=%d skipped=%d rendered=%dB dce_warm=%s %dms", filename, owner,
                     ing.archive_id[:19], len(ing.entries), len(ing.included), len(ing.skipped), len(content), json.dumps(warmed), int((time.monotonic() - t0) * 1000))
            meta = {"forge_zip": True, "archive_id": ing.archive_id, "file_count": len(ing.entries), "included": len(ing.included),
                    "skipped": len(ing.skipped), "truncated": ing.truncated, "source": filename}
            return JSONResponse({"page_content": content, "metadata": meta}, headers={"Cache-Control": "no-store"})
        if zipingest._is_text_type(filename) or mime.startswith("text/") or mime in ("application/json", "application/xml", "application/yaml"):
            decoded = zipingest.decode_text(raw)
            if decoded is None:
                raise POCError(415, "UNSUPPORTED_MEDIA", "File declared as text but contains binary content")
            text, how = decoded
            if filename.lower().endswith((".html", ".htm")):
                text, how = edgar.html_to_paragraph_text(text), "html_text"
            log.info("ingest %s user=%s text passthrough %dB (%s)", filename, owner, len(text), how)
            return JSONResponse({"page_content": text, "metadata": {"forge_zip": False, "source": filename, "rendered": how}},
                                headers={"Cache-Control": "no-store"})
        raise POCError(415, "UNSUPPORTED_MEDIA", f"forge-squid ingestion handles .zip archives and text files; '{mime or 'unknown'}' is not extracted")

    def _text_sources_as_ingests(ctx: attach.Context) -> list[zipingest.Ingest]:
        """Plain (non-ZIP) attachments become single-file pseudo-archives so retrieval and provenance are uniform."""
        out = []
        for s in ctx.texts:
            body = s.body.strip("\n")
            if not body.strip():
                continue
            rid = s.attrs.get("resource-id", "")
            name = s.name or (f"attachment-{rid[:8]}.txt" if rid else f"source-{s.sid or len(out) + 1}.txt")
            ing = zipingest.Ingest(archive_id=zipingest._sha(body.encode("utf-8")), filename=name)
            ing.entries.append(zipingest.Entry(path=name, normalized_name=name, mime="text/plain", bytes=len(body.encode()),
                                               sha256=ing.archive_id, status="INCLUDED", lines=body.count("\n") + 1,
                                               content_sha256=ing.archive_id, rendered="text"))
            ing.files[name] = body
            ing.integrity[name] = "OK"
            out.append(ing)
        return out

    async def attachment_run(request: Request, body: dict[str, Any], user_text: str, ctx: attach.Context):
        """Attachment lane: manifest/listing and retrieval are zero-model; at most one atomic Q2 decision, quote-verified."""
        run_id = uuid.uuid4().hex
        query = ctx.query or "List the files."
        # decision 5 (2026-11-06): the conversation key (Open WebUI chat id → X-Forge-Chat-Id → history hash) lets an
        # elliptical follow-up be read against the previous turn — visibly, the rewrite is printed above the answer.
        asked = query
        sess_key, sess_source = dce_session.conversation_key(request.headers, body.get("messages"))
        follow_up = dce_session.resolve_follow_up(query, dce_store.last(sess_key)) if cfg.dce_mode == "on" else None
        if follow_up is not None:
            query = follow_up.rewritten
        ings_all = ctx.zips + _text_sources_as_ingests(ctx)
        seen: set[str] = set()
        ings = [i for i in ings_all if not (i.archive_id in seen or seen.add(i.archive_id))]  # Open WebUI repeats chat files per turn
        # A text source named *.zip was extracted by Open WebUI's own pipeline before the external ZIP ingestion was enabled.
        stale = sorted({i.filename for i in ings if i not in ctx.zips and i.filename.lower().endswith(tuple(zipingest.ARCHIVE_EXTENSIONS))})
        steps: list[dict[str, Any]] = []
        record: dict[str, Any] = {
            "run_id": run_id, "kind": "attachment", "model_alias": _response_model(), "backend_model": cfg.backend_model,
            "raw_prompt_sha256": hashlib.sha256(user_text.encode()).hexdigest(), "query": query[:500],
            "archives": [{"archive_id": i.archive_id, "filename": i.filename, "entries": len(i.entries), "included": len(i.included),
                          "integrity": dict(i.integrity)} for i in ings],
            "status": "RUNNING", "stages": ["accepted"], "steps": steps,
            "session": {"source": sess_source, "user_ref": dce_session.user_ref(request.headers),   # hash only; never name/email
                        "follow_up": None if follow_up is None else {"kind": follow_up.kind, "asked": asked[:300], "read_as": query[:300]}},
        }
        if len(traces) >= 100:
            traces.pop(next(iter(traces)))
        traces[run_id] = record
        headers = {"X-Forge-Run-Id": run_id, "Cache-Control": "no-store"}
        if not ings:
            record["status"] = "FAILED"
            raise POCError(422, "ATTACHMENT_EMPTY", f"Attached context carried no readable files (run {run_id})")
        bad = [(i.filename, p, st) for i in ings for p, st in i.integrity.items() if st != "OK"]
        steps.append({"node": "ingest", "routing": "zero_model", "status": "COMMITTED",
                      "detail": f"{len(ings)} archive(s), {sum(len(i.included) for i in ings)} readable file(s), "
                                f"{sum(len(i.skipped) for i in ings)} skipped, {len(bad)} integrity problem(s)"})
        record["stages"].append("attachment_parsed")

        # 10-K inside the archive -> existing graph executor with the attached file as DCS source (no EDGAR fetch).
        directive = edgar.parse_directive(query)
        if directive or re.search(r"\b10-?K\b", query, re.I):
            for ing in ings:
                for e in ing.included:
                    txt = ing.files.get(e.path)
                    if txt and ing.integrity.get(e.path) == "OK" and TEN_K_MARK.search(txt[:60000]):
                        data = txt.encode("utf-8")
                        fid = f"sec-zip-{ing.archive_id[7:19]}-{e.sha256[7:15]}" if e.sha256 else f"sec-zip-{ing.archive_id[7:19]}"

                        async def zip_source(client, _data=data, _fid=fid, _e=e, _ing=ing):
                            return _fid, _data, {"kind": "attachment", "archive": _ing.filename, "archive_id": _ing.archive_id,
                                                 "path": _e.path, "sha256": _e.sha256, "bytes": len(_data)}

                        traces.pop(run_id, None)
                        return await graph_run(request, body, user_text, directive=directive or (None, None), source_loader=zip_source,
                                               extra_record={"attachment_run": run_id})
            if directive:
                # The question *mentions* a 10-K and a ticker but the archive holds no 10-K: it is a question about
                # the attached files (e.g. "what was the recall on the NVDA 10-K etalon?"), not an extraction order.
                # Fall through to the attachment lane instead of failing the turn; the trace keeps the reason.
                record["stages"].append("no_10k_in_attachment")
                record["directive_ignored"] = {"ticker": directive[0], "accession": directive[1], "reason": "no 10-K document inside the attachment"}

        # ---- DCE-04: shadow / on (10-K requests above stay on the legacy graph lane in every mode) -------------
        plan: dce_shadow.Plan | None = None
        if cfg.dce_mode != "off":
            plan = await dce_plan(ings, query, run_id, record)
            record["stages"].append("dce_planned" if plan else "dce_plan_failed")
        use_dce = cfg.dce_mode == "on" and plan is not None
        if cfg.dce_mode == "on" and plan is None:
            record["dce"]["fallback"] = "legacy_lane"   # explicit, visible below; never silent

        # ---- live-streamed body ---------------------------------------------------------------------------
        stream = bool(body.get("stream"))
        lg = live.LiveGraph(run_id, "attachment")
        llm_engine = _backend_label(cfg)
        terms, paths = attach.query_terms(query)
        listing = attach.is_list_request(query) or (not terms and not paths)  # small talk ("hi") with a file -> show the manifest
        want_qa = not listing or bool(paths) or len(terms) >= 2
        question = attach.qa_question(query) if want_qa else query  # listing / guidance sentences are handled zero-model
        injection = bool(want_qa and attach.INJECTION_INTENT_RE.search(question))
        describing = bool(want_qa and not injection and not paths and attach.is_describe_request(question))
        n_files = sum(len(i.included) for i in ings)
        n_ing = lg.add("ingest", "zero_model", "forge-zip.v1 manifest parser + SHA-256 block check")
        lg.finish("ingest", "COMMITTED", f"{len(ings)} archive(s), {n_files} readable file(s), "
                                         f"{sum(len(i.skipped) for i in ings)} skipped, {len(bad)} integrity problem(s)")
        if listing:
            lg.add("manifest", "zero_model", "manifest table rendered from the parsed archive")
        if want_qa:
            if injection:
                lg.add("scan", "zero_model", "instruction lexicon scan (regex); no neural NLP model")
            elif describing:
                lg.add("overview", "zero_model", "first heading per file (deterministic digest)")
            else:
                lg.add("retrieve", "zero_model", "token-overlap line retriever; no neural NLP model")
            lg.add("decide", "fixed_model", llm_engine)
            lg.add("verify", "zero_model", "verbatim quote check against path:line (SHA-verified text)")
        record["steps"] = lg.steps()

        state: dict[str, Any] = {"decision": None, "hits": [], "note": "", "failed": False}

        async def body_gen():
            """Yields ('text', md) and ('snap', html-block) pieces in run order; LLM call is visibly bracketed."""
            decision: dict[str, Any] | None = None
            hits: list[attach.Hit] = []
            note = ""
            yield "text", (f"**forge-squid attachment lane** · run `{run_id}` · backend `{cfg.backend_model}`  \n"
                           "Nodes run top-down; only `decide` is an LLM call — everything else is deterministic Python "
                           "(no embedding/NER/classifier models are used in this PoC).\n")
            yield "snap", lg.snapshot_html()
            yield "text", "\n**Live timeline:**\n" + lg.line(n_ing, "end")
            if listing:
                n = lg.start("manifest")
                yield "text", lg.line(n, "start")
                md = "".join(zipingest.render_manifest_markdown(ing) for ing in ings)
                if not terms and not paths and not attach.is_list_request(query):
                    md += ("Ask about the contents, e.g. *\"What does `README.md` say about …?\"*, *\"Quote the exact … from `<path>`\"*, "
                           "or *\"Extract the most impactful statements from the SEC 10-K form in this archive.\"*\n")
                lg.finish("manifest", "COMMITTED", f"{sum(len(i.entries) for i in ings)} entries listed")
                record["stages"].append("manifest_rendered")
                yield "text", lg.line(n, "end")
                yield "text", "\n" + md
            if want_qa:
                if injection:
                    # Questions about embedded instructions are answered by a deterministic scan: the suspicious lines are
                    # reported verbatim as evidence and never shown to the model, so there is nothing to "follow".
                    n = lg.start("scan")
                    yield "text", lg.line(n, "start")
                    hits = attach.scan_injections(ings)
                    record["injection_hits"] = [{"path": h.path, "line": h.line} for h in hits]
                    lg.finish("scan", "COMMITTED", f"{len(hits)} instruction-like line(s) found by lexicon scan")
                    yield "text", lg.line(n, "end")
                    files = sorted({h.path for h in hits})
                    decision = {"found": True,
                                "answer": f"Yes. {len(hits)} line(s) in {', '.join(f'`{f}`' for f in files)} contain instruction-like text addressed to the assistant. "
                                          "They were identified by a deterministic scan, treated as untrusted data and not followed.",
                                "quotes": [{"path": h.path, "line": h.line, "text": h.text} for h in hits]}
                    lg.finish("decide", "SKIPPED", "injection question answered zero-model from the scan; LLM not called")
                    yield "text", lg.line(lg.get("decide"), "end")
                    lg.finish("verify", "COMMITTED", f"{len(hits)} quote(s) are file lines by construction")
                    yield "text", lg.line(lg.get("verify"), "end")
                else:
                    q = question
                    if describing:
                        n = lg.start("overview")
                        yield "text", lg.line(n, "start")
                        yield "text", "\n" + attach.render_overview(ings) + "\n"
                        hits = attach.overview_hits(ings)
                        q = ("Based only on these headline lines, what is this archive about? Answer in one sentence "
                             "and quote the lines that support it.")
                        lg.finish("overview", "COMMITTED", f"{len(hits)} headline line(s) (first heading per file) as the model's only input")
                    else:
                        n = lg.start("retrieve")
                        yield "text", lg.line(n, "start")
                        hits = attach.retrieve(ings, q)
                        lg.finish("retrieve", "COMMITTED", f"{len(hits)} excerpt(s) for {len(terms)} term(s), {len(paths)} named path(s)")
                    yield "text", lg.line(n, "end")
                    record["question"] = q[:500]
                    record["hits"] = [{"path": h.path, "line": h.line, "score": h.score} for h in hits]
                    if not hits:
                        names = [f"`{e.path}`" for i in ings for e in i.included][:12]
                        decision = {"found": False, "quotes": [],
                                    "answer": "No file line shares a word with the question, so nothing was sent to the model. "
                                              f"Attached text: {', '.join(names) or 'none'}. Ask about something those files contain, "
                                              "e.g. *\"What does `<path>` say about <topic>?\"* or *\"Quote the exact <thing> from `<path>`\"*."}
                        lg.finish("decide", "SKIPPED", "no excerpts -> zero-model not-found; LLM not called")
                        yield "text", lg.line(lg.get("decide"), "end")
                        lg.finish("verify", "COMMITTED", "nothing to verify")
                        yield "text", lg.line(lg.get("verify"), "end")
                    else:
                        async with run_sem:
                            async with httpx.AsyncClient(transport=transport, timeout=cfg.llm_timeout, follow_redirects=False) as client:
                                try:
                                    trace_meta = await check_backend(client)
                                except POCError as ex:
                                    record["status"] = "FAILED"
                                    raise POCError(ex.status, ex.code, f"{ex.message} (run {run_id})") from ex
                                record["upstream_catalog"] = trace_meta.get("catalog_trace")
                                hint: str | None = None
                                attempts: list[dict[str, Any]] = []
                                nd = lg.start("decide", f"{len(hits)} excerpt(s) in prompt, max_tokens 400")
                                for attempt in range(1, cfg.max_attempts + 1):
                                    msgs = attach.qa_messages(q, hits, retry_hint=hint)
                                    nd.detail = f"attempt {attempt}/{cfg.max_attempts} · {len(hits)} excerpt(s) in prompt · max_tokens 400"
                                    yield "text", lg.line(nd, "start")
                                    yield "snap", lg.snapshot_html()  # the LLM is in flight: timer ticks in the artifact
                                    t0 = time.monotonic()
                                    try:
                                        answer = await complete_backend(
                                            client,
                                            {"model": _effective_backend_model(cfg), "messages": msgs, "temperature": 0, "max_tokens": 400, "stream": False},
                                        )
                                        served = str(answer.get("model", ""))
                                        content = str(answer["choices"][0]["message"]["content"])
                                    except (POCError, KeyError, IndexError, TypeError) as ex:
                                        attempts.append({"attempt": attempt, "failure": f"UPSTREAM:{type(ex).__name__}"})
                                        hint = "upstream error"
                                        yield "text", f"  - ✗ upstream error ({type(ex).__name__}); retrying\n"
                                        continue
                                    ms = int((time.monotonic() - t0) * 1000)
                                    if not _backend_matches(served, _effective_backend_model(cfg)):
                                        attempts.append({"attempt": attempt, "failure": "BACKEND_MODEL_MISMATCH", "served": served})
                                        yield "text", f"  - ✗ served model `{served}` is not the pinned backend; aborting\n"
                                        break
                                    try:
                                        cand = attach.parse_qa(content)
                                    except (ValueError, json.JSONDecodeError) as ex:
                                        attempts.append({"attempt": attempt, "failure": f"DECISION_INVALID:{str(ex)[:60]}", "raw": content[:400], "ms": ms})
                                        hint = str(ex)[:80]
                                        yield "text", f"  - ✗ {ms} ms, output not valid JSON ({str(ex)[:60]}); retrying\n"
                                        continue
                                    problems = attach.verify_quotes(cand, hits)
                                    if problems:
                                        attempts.append({"attempt": attempt, "failure": "QUOTE_NOT_VERBATIM", "problems": problems, "raw": content[:400], "ms": ms})
                                        hint = problems[0]
                                        yield "text", f"  - ✗ {ms} ms, quote not verbatim ({problems[0][:60]}); retrying\n"
                                        continue
                                    cand["found"] = bool(cand["quotes"])  # verified evidence decides the flag, not the model's opinion
                                    cand["model_output"] = {"served": served, "ms": ms, "attempt": attempt, "raw": content[:600],
                                                            "label": "Model summary" if describing else "Model answer"}
                                    attempts.append({"attempt": attempt, "status": "COMMITTED", "ms": ms, "served": served,
                                                     "prompt_sha256": hashlib.sha256(json.dumps(msgs, sort_keys=True).encode()).hexdigest()})
                                    decision = cand
                                    break
                                record["decision_attempts"] = attempts
                                if decision is None:
                                    lg.finish("decide", "FAILED", f"{len(attempts)} attempt(s) rejected: {attempts[-1].get('failure') if attempts else 'none'}")
                                    yield "text", lg.line(nd, "end")
                                    lg.finish("verify", "FAILED", "no verified decision; nothing committed")
                                    note = "Run failed: the model's answer could not be verified against the excerpts; no result committed."
                                else:
                                    lg.finish("decide", "COMMITTED", f"1 atomic Q2 call ({attempts[-1]['served']}), {attempts[-1]['ms']} ms, attempt {len(attempts)}")
                                    yield "text", lg.line(nd, "end")
                                    nv = lg.start("verify")
                                    lg.finish("verify", "COMMITTED", f"{len(decision['quotes'])} quote(s) verbatim-checked against path:line")
                                yield "text", lg.line(lg.get("verify"), "end")
            if bad:
                note = (note + " " if note else "") + f"Integrity problems excluded {len(bad)} file(s): " + ", ".join(f"{p} ({st})" for _, p, st in bad[:5])
            if stale:
                note = (note + " " if note else "") + (f"{', '.join(f'`{s}`' for s in stale)} was uploaded before ZIP ingestion was enabled and is held as "
                                                      "plain text; re-attach the archive in a new message to get the per-file manifest.")
            failed = want_qa and decision is None
            state.update(decision=decision, hits=hits, note=note, failed=failed)
            record["status"] = "FAILED" if failed else "COMMITTED"
            record["decision"] = decision
            record["steps"] = lg.steps()
            record["stages"].append("run_failed" if failed else "atomic_commit")
            lg.close(record["status"])
            if plan is not None:   # shadow: legacy result is final; record where DCE would have differed (trace only)
                legacy_lane = "scan" if injection else "overview" if describing else "retrieve" if want_qa else "manifest"
                record["dce"]["comparison"] = dce_shadow.compare_with_legacy(record["dce"], {
                    "lane": legacy_lane, "hits": [f"{h.path}:{h.line}" for h in hits], "found": (decision or {}).get("found") if want_qa else None,
                    "llm_calls": len(record.get("decision_attempts") or []), "status": record["status"]})
                record["dce"]["status"] = "SHADOWED"
            yield "text", f"- ■ `{lg.elapsed_ms() / 1000:6.2f} s` run {record['status']}\n\n"
            if want_qa:
                yield "text", attach.render_answer(run_id, ctx, decision, hits, lg.steps(), note=note)
            else:
                if note:
                    yield "text", f"_{note}_\n"
                yield "text", attach.render_log(run_id, lg.steps(), [])
            if cfg.dce_mode == "on" and plan is None:
                yield "text", f"\n_DCE mode is `on` but planning failed ({record['dce'].get('status')}); this answer came from the legacy attachment lane._\n"
            yield "snap", lg.snapshot_html(final=True)
            log.info("attachment run %s: %s listing=%s qa=%s hits=%d %dms", run_id, record["status"], listing, want_qa, len(hits), lg.elapsed_ms())

        async def dce_body_gen():
            """DCE-04 `on`: DAG execution with the merge/verification gate. Same ('text'|'snap') protocol as the legacy body."""
            assert plan is not None
            record["kind"] = "attachment"
            record["lane"] = "dce"
            lgd = live.LiveGraph(run_id, "attachment-dce")
            for n in plan.dag.nodes:
                engine = "fixed_model" if n.route_pref in ("D1", "D2") else "zero_model"
                lgd.add(n.id, engine, f"{n.kind} · {n.route_pref}" + (f" · {llm_engine}" if engine == "fixed_model" else ""))
            record["steps"] = lgd.steps()
            yield "text", (f"**forge-squid attachment lane (DCE)** · run `{run_id}` · backend `{cfg.backend_model}`  \n"
                           f"{len(plan.dag.nodes)} typed nodes, {plan.dag.model_calls_planned} model call(s) planned (cap {cfg.dce_max_model_calls}); "
                           "D0 nodes are deterministic Python over the verified attachment map.\n")
            yield "snap", lgd.snapshot_html()
            yield "text", "\n**Live timeline:**\n"
            needs_model = any(n.route_pref in ("D1", "D2") and n.budget["calls"] for n in plan.dag.nodes)
            client_cm = httpx.AsyncClient(transport=transport, timeout=cfg.llm_timeout, follow_redirects=False) if needs_model else None
            call_llm = None
            client = None
            if client_cm is not None:
                client = await client_cm.__aenter__()
                try:
                    trace_meta = await check_backend(client)
                except POCError as ex:
                    await client_cm.__aexit__(None, None, None)
                    record["status"] = "FAILED"
                    raise POCError(ex.status, ex.code, f"{ex.message} (run {run_id})") from ex
                record["upstream_catalog"] = trace_meta.get("catalog_trace")

                async def call_llm(msgs: list[dict[str, str]], *, max_tokens: int = dce_shadow.Q2_MAX_TOKENS) -> tuple[str, str]:
                    answer = await complete_backend(
                        client,
                        {"model": _effective_backend_model(cfg), "messages": msgs, "temperature": 0, "max_tokens": max_tokens, "stream": False},
                    )
                    served = str(answer.get("model", ""))
                    if not _backend_matches(served, _effective_backend_model(cfg)):
                        raise POCError(502, "BACKEND_MODEL_MISMATCH", "Gateway returned a different served model")
                    return str(answer["choices"][0]["message"]["content"]), served

            lines: list[str] = []

            async def on_node(r: dce_shadow.NodeResult) -> None:
                lgd.start(r.node_id)
                lgd.finish(r.node_id, r.status if r.status in ("COMMITTED", "PARTIAL") else "SKIPPED" if r.status in ("SKIPPED", "UNSUPPORTED") else "FAILED",
                           f"{r.route} · {r.method or r.kind} · {r.status}" + (f" · {r.model_calls} call(s)" if r.model_calls else "") + (f" · {r.detail[:80]}" if r.detail else ""))
                lines.append(lgd.line(lgd.get(r.node_id), "end"))

            try:
                async with run_sem:
                    results = await dce_shadow.execute(plan, ings, call_llm, dce_budget, on_node=on_node)
            finally:
                if client_cm is not None:
                    await client_cm.__aexit__(None, None, None)
            for ln in lines:
                yield "text", ln
            gate = dce_shadow.merge_gate(plan, results)
            record["dce"]["status"] = gate["status"]
            record["dce"]["gate"] = {k: gate[k] for k in ("status", "goals", "span_problems", "model_calls_made", "nodes")}
            record["dce"]["model_calls_made"] = gate["model_calls_made"]
            record["dce"]["results"] = dce_shadow.results_trace(results)
            record["status"] = "COMMITTED" if gate["status"] == "COMMITTED" else "FAILED" if gate["status"] == "FAILED" else "PARTIAL"
            record["steps"] = lgd.steps()
            record["stages"].append({"COMMITTED": "atomic_commit", "PARTIAL": "partial_commit", "FAILED": "run_failed"}[gate["status"]])
            lgd.close("COMMITTED" if gate["status"] != "FAILED" else "FAILED")
            yield "text", f"- ■ `{lgd.elapsed_ms() / 1000:6.2f} s` run {gate['status']}\n\n"
            if bad or stale:
                extra = []
                if bad:
                    extra.append(f"Integrity problems excluded {len(bad)} file(s): " + ", ".join(f"{p} ({st})" for _, p, st in bad[:5]))
                if stale:
                    extra.append(f"{', '.join(f'`{s}`' for s in stale)} was uploaded before ZIP ingestion was enabled and is held as plain text.")
                yield "text", "_" + " ".join(extra) + "_\n"
            if follow_up is not None:
                yield "text", f"_Follow-up {follow_up.note}._\n\n"
            rendered = dce_shadow.render(run_id, plan, results, gate, backend_model=cfg.backend_model)
            dce_store.push(sess_key, dce_session.turn_from_results(asked, query, record["dce"]["results"], rendered, [i.filename for i in ings]))
            yield "text", rendered
            yield "snap", lgd.snapshot_html(final=True)
            log.info("attachment run %s (dce): %s goals=%d calls=%d %dms", run_id, gate["status"], len(gate["goals"]), gate["model_calls_made"], lgd.elapsed_ms())

        gen_fn = dce_body_gen if use_dce else body_gen

        if not stream:
            parts: list[str] = []
            last_snap = ""
            async for kind, piece in gen_fn():
                if kind == "snap":
                    last_snap = piece  # JSON clients get the final graph only
                else:
                    parts.append(piece)
            return _text_response(body, run_id, "".join(parts) + last_snap, headers)

        created = int(time.time())
        response_id = "chatcmpl-" + run_id

        def chunk(delta: dict[str, str], finish: str | None = None) -> str:
            frame = {"id": response_id, "object": "chat.completion.chunk", "created": created, "model": _response_model(),
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

        async def generate():
            yield chunk({"role": "assistant"})
            try:
                async for _kind, piece in gen_fn():
                    yield chunk({"content": piece})
            except POCError as ex:
                record["status"] = "FAILED"
                record["stages"].append("run_failed")
                lg.close("FAILED")
                yield chunk({"content": f"\n\n**Run failed:** `{ex.code}` — {ex.message}. No result committed.\n"})
                yield chunk({"content": lg.snapshot_html(final=True)})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)

    def _chat_experiment_headers(req: Request) -> dict[str, str] | None:
        keys = ("sanitize", "prose_only", "continue", "stream_graph")
        hdrs: dict[str, str | None] = {}
        for k in keys:
            slug = k.replace("_", "-")
            hdrs[k] = req.headers.get(f"x-forge-squid-exp-{slug}") or req.headers.get(f"x-forge-2b-exp-{slug}")
        if all(v is None for v in hdrs.values()):
            return None
        return {k: (v if v is not None else "") for k, v in hdrs.items()}

    async def free_chat(request: Request, body: dict[str, Any], messages: Any, user_text: str):
        """Ordinary conversation. A side-effect-only ask is answered from the reader; every other ask is one pinned-model reply.

        The lane exposes forge-squid value-add on the right: comprehension (`read`), prose profile + prompt assembly
        (`profile`, `compose`), one or more pinned-model calls (`reply`, optional `reply_cont` / `reply_refine`), then
        deterministic shaping (`polish`). JSON clients get the final graph; streaming clients see nodes accumulate and the
        active LLM step tick while the model is in flight (P1.3+, 2026-11-11)."""
        exp_token = set_chat_experiment(_chat_experiment_headers(request))
        note_hdr = request.headers.get("x-forge-squid-contract-note") or request.headers.get(
            "x-forge-2b-contract-note"
        )
        note_token = set_contract_note_override(note_hdr.strip().lower() if note_hdr else None)
        try:
            return await _free_chat_inner(request, body, messages, user_text, exp_token)
        finally:
            reset_contract_note_override(note_token)
            reset_chat_experiment(exp_token)

    async def _free_chat_inner(request: Request, body: dict[str, Any], messages: Any, user_text: str, _exp_token: object):
        route_client = _client_model.get()
        route_upstream = _upstream_model.get()
        reading = relax_answer_shaping(comprehend(user_text), user_text)
        structured = is_structured_contract(user_text)
        prose_prof = prose_profile(reading, user_text)
        decision = reading.decision()
        use_dag = chat_plan_enabled() and not structured and decision in ("chat", "constrained")
        run_id = uuid.uuid4().hex
        lg: live.LiveGraph | None = None
        eg: execution_graph.ExecutionGraph | None = None
        if not use_dag:
            lg = live.LiveGraph(run_id, "chat")
            lg.add("read", "zero_model", "request_ir + DCE-01 · side-effect lexicon")
            lg.start("read")
        record: dict[str, Any] = {
            "run_id": run_id,
            "model_alias": _response_model(),
            "backend_model": cfg.backend_model,
            "kind": "chat",
            "lane": "chat",
            "raw_prompt_sha256": hashlib.sha256(user_text.encode()).hexdigest(),
            "status": "RUNNING",
            "attempts": 0,
            "stages": ["accepted", "comprehended"],
            "reading": trace_reading(reading),
            "prose_profile": prose_prof.value,
            "steps": [],
        }
        if len(traces) >= 100:
            traces.pop(next(iter(traces)))
        traces[run_id] = record
        if lg is not None:
            record["steps"] = lg.steps()
        headers = {"Cache-Control": "no-store", "X-Forge-Lane": "chat", "X-Forge-Run-Id": run_id}
        timeline: list[str] = []

        def done(node: str, status: str, detail: str, run_status: str) -> str:
            assert lg is not None
            """Close `node` and the run; returns the Live timeline + final graph that ends every chat answer."""
            lg.finish(node, status, detail)
            timeline.append(lg.line(lg.get(node), "end"))
            lg.close(run_status)
            record["steps"] = lg.steps()
            graph = "\n\n**Live timeline:**\n" + "".join(timeline) + lg.snapshot_html(final=True)
            if not chat_stream_graph():
                record["presentation_graph"] = lg.snapshot_html(final=True)
                return ""
            return graph

        def commit_deterministic(node_id: str, engine: str, detail: str) -> None:
            assert lg is not None
            lg.add(node_id, "zero_model", engine)
            lg.start(node_id)
            lg.finish(node_id, "COMMITTED", detail)
            timeline.append(lg.line(lg.get(node_id), "end"))
            record["steps"] = lg.steps()

        def seal_graph(run_status: str) -> str:
            assert lg is not None
            lg.close(run_status)
            record["steps"] = lg.steps()
            graph = "\n\n**Live timeline:**\n" + "".join(timeline) + lg.snapshot_html(final=True)
            if not chat_stream_graph():
                record["presentation_graph"] = lg.snapshot_html(final=True)
                return ""
            return graph

        def seal_dag(eg_run: execution_graph.ExecutionGraph, run_status: str, *, stream_append: bool) -> str:
            eg_run.close(run_status)
            record["steps"] = eg_run.steps()
            record["execution_graph"] = eg_run.to_trace()
            graph = "\n\n**Live timeline:**\n" + "".join(timeline) + eg_run.snapshot_html(final=True)
            record["presentation_graph"] = eg_run.snapshot_html(final=True)
            if not chat_stream_graph() or not stream_append:
                return graph if (chat_stream_graph() and not stream_append) else ""
            return graph

        if lg is not None:
            goals_preview = ", ".join(reading.dce_goals[:4]) or "—"
            if len(reading.dce_goals) > 4:
                goals_preview += f" +{len(reading.dce_goals) - 4}"
            lg.finish(
                "read",
                "COMMITTED",
                f"decision {decision} · route {reading.dce_route} · {len(reading.objectives)} objective(s) · goals {goals_preview}",
            )
            timeline.append(lg.line(lg.get("read"), "end"))
        if decision == "refuse":
            assert lg is not None
            record["status"] = "REFUSED_SIDE_EFFECT"
            record["stages"].append("side_effect_refused")
            lg.add("refuse", "zero_model", "reader verdict · no model")
            lg.start("refuse")
            return _text_response(body, run_id, refusal_text(reading) + done("refuse", "COMMITTED", "side effect requested — not performed", "REFUSED_SIDE_EFFECT"), headers)
        named = identity_reply(user_text)
        if named is not None:
            assert lg is not None
            record["status"] = "COMMITTED"
            record["stages"].append("identity")
            record["reading"]["decision"] = "identity"
            lg.add("identity", "zero_model", "fixed self-description · no model")
            lg.start("identity")
            return _text_response(body, run_id, named + done("identity", "COMMITTED", "who-are-you answered without the model", "COMMITTED"), headers)
        # Phase 5 grounding (2026-11-06): questions about the engine itself, about what is attached, about the previous turn, and
        # elliptical follow-ups that arrived without their attachment are answered deterministically from the session store —
        # the pinned model is never asked about files it cannot see or about capabilities it would invent.
        sess_key, sess_source = dce_session.conversation_key(request.headers, messages)
        prev = dce_store.last(sess_key)
        prev_att = dce_store.last(sess_key, "attachment")   # the last turn answered from a file, even after chat turns in between
        follow_up = dce_session.resolve_follow_up(user_text, prev_att) if prev_att is not None and prev is prev_att else None
        record["session"] = {"source": sess_source, "user_ref": dce_session.user_ref(request.headers),
                             "previous_turn": {"lane": prev.lane, "asked": prev.asked[:200], "archives": list(prev.archives)} if prev else None,
                             "follow_up": {"kind": follow_up.kind, "asked": user_text[:200], "read_as": follow_up.rewritten[:300]} if follow_up else None}
        for stage, text in (("capabilities", capabilities_reply(user_text)), ("attached_state", attached_state_reply(user_text, prev_att)),
                            ("previous_answer", previous_answer_reply(user_text, prev)), ("detached_follow_up", detached_follow_up_reply(user_text, prev_att, follow_up))):
            if text is not None:
                record["status"] = "COMMITTED"
                record["stages"].append(stage)
                record["reading"]["decision"] = stage
                assert lg is not None
                lg.add(stage, "zero_model", "session store · no model")
                lg.start(stage)
                return _text_response(body, run_id, text + done(stage, "COMMITTED", f"{stage.replace('_', ' ')} answered without the model", "COMMITTED"), headers)

        conv = conversation(messages) or [{"role": "user", "content": user_text[:4000]}]
        system_bits = system_prompt(reading, previous_turn_note(prev)) + json_instruction(user_text) + contract_note(user_text)
        stream_mode = bool(body.get("stream"))

        if use_dag:
            eg, objectives = bootstrap_graph(run_id, user_text, reading, decision)
            record["stages"].append("comprehension_dag")
            eg.add("profile", "zero_model", "prose_turn", lane="plan", kind="role_pick")
            eg.finish("profile", "COMMITTED", f"prose profile · {prose_prof.value}")
            eg.add_edge("route", "profile")
            plan = compile_plan(
                user_text, reading, objectives, prose_prof, _response_model(), structured=structured
            )
            record["chat_plan"] = plan.to_dict()
            emit_plan_band(eg, plan)
            record["steps"] = eg.steps()

            async def call_llm(msgs: list[dict[str, str]]) -> tuple[str, str]:
                async with run_sem:
                    async with httpx.AsyncClient(
                        transport=transport, timeout=cfg.llm_timeout, follow_redirects=False
                    ) as client:
                        answer = await complete_backend(
                            client,
                            {
                                "model": _effective_backend_model(cfg),
                                "messages": msgs,
                                "temperature": 0,
                                "max_tokens": 1024,
                                "stream": False,
                            },
                        )
                choice = answer["choices"][0]
                piece = flatten_content((choice.get("message") or {}).get("content")) or ""
                served = str(answer.get("model", ""))
                if not _backend_matches(served, _effective_backend_model(cfg)):
                    raise POCError(502, "BACKEND_MODEL_MISMATCH", "Gateway returned a different served model")
                if not piece.strip():
                    raise POCError(502, "INVALID_GATEWAY_RESPONSE", "Gateway response has no assistant content")
                return piece.strip(), served

            async def dag_reply(*, attach_graph_in_body: bool) -> str:
                text, fails, calls = await execute_chat_plan(
                    eg,
                    plan,
                    user_text=user_text,
                    reading=reading,
                    prose_prof=prose_prof,
                    conv=conv,
                    structured=structured,
                    call_llm=call_llm,
                    system_base=system_bits,
                )
                for n in eg.nodes:
                    if n.status == "RUNNING":
                        timeline.append(eg.line(n, "end"))
                record["attempts"] = calls
                record["prose_gates"] = fails
                record["status"] = "COMMITTED"
                record["stages"].append("chat_plan_execute")
                text = present_structured(user_text, text)
                dce_store.push(sess_key, dce_session.chat_turn(user_text, text))
                tail = seal_dag(eg, "COMMITTED", stream_append=not attach_graph_in_body)
                if structured or chat_prose_only():
                    return text
                if attach_graph_in_body:
                    return text
                return text + tail

            if not stream_mode:
                return _text_response(body, run_id, await dag_reply(attach_graph_in_body=False), headers)

            created = int(time.time())
            response_id = "chatcmpl-" + run_id

            def chunk_dag(delta: dict[str, str], finish: str | None = None) -> str:
                frame = {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": _response_model(),
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

            async def generate_dag():
                t_client = _client_model.set(route_client)
                t_upstream = _upstream_model.set(route_upstream)
                try:
                    yield chunk_dag({"role": "assistant"})
                    if chat_stream_graph():
                        yield chunk_dag({"content": eg.snapshot_html()})
                    try:
                        prose = await dag_reply(attach_graph_in_body=True)
                        yield chunk_dag({"content": prose})
                        if chat_stream_graph():
                            yield chunk_dag({"content": eg.snapshot_html(final=True)})
                    except POCError as ex:
                        eg.close("FAILED")
                        fail_tail = eg.snapshot_html(final=True) if chat_stream_graph() else ""
                        yield chunk_dag(
                            {
                                "content": f"\n\n**Run failed:** `{ex.code}` — {ex.message}. No reply committed.\n"
                                + fail_tail
                            }
                        )
                    yield chunk_dag({}, "stop")
                    yield "data: [DONE]\n\n"
                finally:
                    _client_model.reset(t_client)
                    _upstream_model.reset(t_upstream)

            return StreamingResponse(generate_dag(), media_type="text/event-stream", headers=headers)

        if not structured and prose_prof != ProseProfile.PLAIN:
            system_bits += profile_instruction(prose_prof)
        commit_deterministic(
            "profile",
            "prose_turn · profile pick",
            f"prose profile · {prose_prof.value}" + (" · reader constrained" if decision == "constrained" else ""),
        )
        ck = contract_kind(user_text)
        if structured or ck:
            commit_deterministic("contract", "structured_turn", f"contract kind · {ck or 'structured'}")
        compose_bits: list[str] = [f"{len(conv)} chat turn(s)"]
        if prose_prof != ProseProfile.PLAIN and not structured:
            compose_bits.append(f"profile instruction ({prose_prof.value})")
        if decision == "constrained":
            compose_bits.append("side-effect reader note")
        if ck == "json":
            compose_bits.append("json_object response_format")
        commit_deterministic("compose", "prompt assembly", "system prompt · " + " · ".join(compose_bits))
        llm_body = {
            "model": _effective_backend_model(cfg),
            "messages": [{"role": "system", "content": system_bits}, *conv],
            "temperature": 0,
            "max_tokens": 1024,
            "stream": False,
        }
        if contract_kind(user_text) == "json":
            # One completion, same weights. The gateway emits a JSON object and does not spend the
            # reply on a thinking preamble. The schema is "an object", never the expected fields.
            llm_body["response_format"] = {"type": "json_object"}
            llm_body["think"] = False
            llm_body["reasoning_effort"] = "none"
        lg.add("reply", "fixed_model", _effective_backend_model(cfg))

        def failed() -> None:
            assert lg is not None
            record["status"] = "FAILED"
            record["stages"].append("run_failed")
            lg.finish("reply", "FAILED")
            lg.close("FAILED")
            record["steps"] = lg.steps()

        async def reply_text() -> str:
            finish_reason = "stop"
            attempts = 0
            content = ""
            served = ""
            active_llm = "reply"
            try:
                async with run_sem:
                    async with httpx.AsyncClient(transport=transport, timeout=cfg.llm_timeout, follow_redirects=False) as client:
                        msgs = list(llm_body["messages"])
                        while True:
                            attempts += 1
                            if active_llm == "reply_cont":
                                lg.start("reply_cont", "continuation · finish truncated answer")
                            body = {**llm_body, "messages": msgs}
                            try:
                                answer = await complete_backend(client, body)
                            except POCError:
                                if "response_format" not in body:
                                    raise
                                # The gateway 500s on json_object for some long contracts. One plain retry,
                                # same messages, still a single answer the client sees.
                                plain = {k: v for k, v in body.items() if k not in ("response_format", "think", "reasoning_effort")}
                                answer = await complete_backend(client, plain)
                                record["stages"].append("json_mode_fallback")
                                commit_deterministic("json_fallback", "gateway retry", "json_object rejected · plain completion")
                            choice = answer["choices"][0]
                            finish_reason = str(choice.get("finish_reason") or "stop")
                            piece = flatten_content((choice.get("message") or {}).get("content")) or ""
                            served = str(answer.get("model", ""))
                            content = (content + piece).strip() if content else piece.strip()
                            if finish_reason != "length" or not chat_continue_on_length() or attempts > 1 or structured:
                                break
                            lg.finish("reply", "PARTIAL", "finish_reason length · scheduling continuation")
                            timeline.append(lg.line(lg.get("reply"), "end"))
                            record["steps"] = lg.steps()
                            lg.add("reply_cont", "fixed_model", _effective_backend_model(cfg))
                            active_llm = "reply_cont"
                            msgs = [
                                *msgs,
                                {"role": "assistant", "content": piece},
                                {
                                    "role": "user",
                                    "content": "Continue your previous answer where it stopped. Use plain text only; no HTML and no live graphs.",
                                },
                            ]
                record["finish_reason"] = finish_reason
            except POCError:
                failed()
                raise
            except (KeyError, IndexError, TypeError) as ex:
                failed()
                raise POCError(502, "INVALID_GATEWAY_RESPONSE", "Gateway response has no assistant content") from ex
            if not isinstance(content, str) or not content.strip():
                failed()
                raise POCError(502, "INVALID_GATEWAY_RESPONSE", "Gateway response has no assistant content")
            if not _backend_matches(served, _effective_backend_model(cfg)):
                failed()
                raise POCError(502, "BACKEND_MODEL_MISMATCH", "Gateway returned a different served model")
            record["served_model"] = served
            record["attempts"] = attempts
            truncated = finish_reason == "length"
            if truncated and chat_continue_on_length():
                record["status"] = "PARTIAL"
                record["stages"].append("reply_truncated")
            else:
                record["status"] = "COMMITTED"
                record["stages"].append("reply")
            text = visible_prefix(reading) + scrub_self_claim(content.strip()) + footer(reading)
            text = present_structured(user_text, text)
            if not structured:
                text = assemble_prose(prose_prof, text)
                fails = prose_gate(prose_prof, text, truncated=truncated)
                record["prose_gates"] = fails
                if prose_prof == ProseProfile.ENUMERATE and "list_missing" in fails and attempts == 1:
                    retry_msgs = [
                        *llm_body["messages"],
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": enumerate_retry_user_message()},
                    ]
                    try:
                        lg.add("reply_refine", "fixed_model", _effective_backend_model(cfg))
                        lg.start("reply_refine", "enumerate gate · list_missing · 2nd LLM call")
                        record["steps"] = lg.steps()
                        async with run_sem:
                            async with httpx.AsyncClient(
                                transport=transport, timeout=cfg.llm_timeout, follow_redirects=False
                            ) as client:
                                answer = await complete_backend(client, {**llm_body, "messages": retry_msgs})
                        choice = answer["choices"][0]
                        extra = flatten_content((choice.get("message") or {}).get("content")) or ""
                        if extra.strip():
                            attempts += 1
                            record["attempts"] = attempts
                            record["stages"].append("enumerate_retry")
                            lg.finish("reply_refine", "COMMITTED", "enumerate gate retry committed")
                            timeline.append(lg.line(lg.get("reply_refine"), "end"))
                            text = assemble_prose(prose_prof, extra.strip())
                            record["prose_gates"] = prose_gate(prose_prof, text, truncated=False)
                        else:
                            lg.finish("reply_refine", "FAILED", "empty refinement")
                            timeline.append(lg.line(lg.get("reply_refine"), "end"))
                    except (POCError, KeyError, IndexError, TypeError):
                        if any(n.id == "reply_refine" for n in lg.nodes):
                            lg.finish("reply_refine", "FAILED", "refinement error")
                            timeline.append(lg.line(lg.get("reply_refine"), "end"))
            dce_store.push(sess_key, dce_session.chat_turn(user_text, text))
            run_status = record["status"]
            llm_nodes = [n for n in lg.nodes if n.routing == "fixed_model"]
            llm_detail = " · ".join(f"{n.id} {n.status.lower()}" for n in llm_nodes if n.status != "PENDING")
            if active_llm == "reply_cont":
                lg.finish(
                    "reply_cont",
                    "COMMITTED" if run_status == "COMMITTED" else "PARTIAL",
                    f"served {served}" + (" · truncated" if truncated else ""),
                )
                timeline.append(lg.line(lg.get("reply_cont"), "end"))
            else:
                lg.finish(
                    "reply",
                    "COMMITTED" if run_status == "COMMITTED" else "PARTIAL",
                    f"{attempts} call(s) · {llm_detail or 'served ' + served}" + (" · truncated" if truncated else ""),
                )
                timeline.append(lg.line(lg.get("reply"), "end"))
            gate_txt = ", ".join(record.get("prose_gates") or []) or "all gates passed"
            commit_deterministic("polish", "assemble_prose · scrub · gates", gate_txt)
            graph = seal_graph(run_status)
            if structured:
                return text
            if chat_prose_only():
                return text
            if stream_mode:
                return text
            return text + graph

        assert lg is not None
        lg.start("reply", "one pinned-model call over the conversation")
        if not stream_mode:
            return _text_response(body, run_id, await reply_text(), headers)

        created = int(time.time())
        response_id = "chatcmpl-" + run_id

        def chunk(delta: dict[str, str], finish: str | None = None) -> str:
            frame = {"id": response_id, "object": "chat.completion.chunk", "created": created, "model": _response_model(),
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

        async def generate():
            assert lg is not None
            t_client = _client_model.set(route_client)
            t_upstream = _upstream_model.set(route_upstream)
            try:
                yield chunk({"role": "assistant"})
                if chat_stream_graph():
                    yield chunk({"content": lg.snapshot_html()})
                try:
                    prose = await reply_text()
                    if chat_stream_graph():
                        yield chunk({"content": prose})
                        yield chunk({"content": lg.snapshot_html(final=True)})
                    else:
                        yield chunk({"content": prose})
                except POCError as ex:
                    fail_tail = lg.snapshot_html(final=True) if chat_stream_graph() else ""
                    yield chunk({"content": f"\n\n**Run failed:** `{ex.code}` — {ex.message}. No reply committed.\n" + fail_tail})
                yield chunk({}, "stop")
                yield "data: [DONE]\n\n"
            finally:
                _client_model.reset(t_client)
                _upstream_model.reset(t_upstream)

        return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)

    @app.post("/v1/chat/completions")
    async def completion(request: Request):
        require_access(request)
        require_live()
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise POCError(413, "REQUEST_TOO_LARGE", "Request body exceeds PoC limit")
        try:
            body = json.loads(raw)
        except ValueError as ex:
            raise POCError(400, "INVALID_REQUEST", "Body must be valid JSON") from ex
        if not isinstance(body, dict):
            raise POCError(400, "INVALID_REQUEST", "Body must be a JSON object")
        client_model = body.get("model")
        if not isinstance(client_model, str) or not client_model.strip():
            raise POCError(400, "INVALID_REQUEST", "model must be a non-empty string")
        async with httpx.AsyncClient(transport=transport, timeout=30.0, follow_redirects=False) as client:
            catalog = await get_catalog(client)
        client_model, upstream = resolve_client_model(client_model.strip(), catalog)
        messages = body.get("messages")
        user_text = _last_user_text(messages)
        if user_text is None:
            raise POCError(422, "UNSUPPORTED_CHAT", "PoC accepts plain-text user messages only")
        if body.get("tools") or body.get("tool_choice") or body.get("response_format"):
            raise POCError(422, "UNSUPPORTED_FEATURE", "Tools and client-supplied output schemas are outside first PoC")
        if body.get("stream") not in (None, True, False):
            raise POCError(422, "INVALID_REQUEST", "stream must be boolean")

        async with request_route(client_model, upstream):
            ctx = attach.parse_openwebui_context(user_text)
            if ctx is not None and ctx.sources:
                return await attachment_run(request, body, user_text, ctx)
            task_answer = attach.task_response(user_text)
            if task_answer is not None:  # Open WebUI housekeeping prompts: zero-model, never inference
                return _text_response(body, uuid.uuid4().hex, task_answer, {"Cache-Control": "no-store", "X-Forge-Lane": "task"})
            if edgar.parse_directive(user_text) and "SOURCE:" not in user_text:
                return await graph_run(request, body, user_text)
            if not SOURCE_PATTERN.fullmatch(user_text):
                return await free_chat(request, body, messages, user_text)
            expected, source = parse_fixture(user_text)
            run_id = uuid.uuid4().hex

            async with run_sem:
                record: dict[str, Any] = {
                    "run_id": run_id,
                    "model_alias": _response_model(),
                    "backend_model": _effective_backend_model(cfg),
                    "upstream_model": upstream,
                    "raw_prompt_sha256": hashlib.sha256(user_text.encode()).hexdigest(),
                    "status": "RUNNING",
                    "attempts": 0,
                    "stages": ["accepted"],
                }
                if len(traces) >= 100:
                    traces.pop(next(iter(traces)))
                traces[run_id] = record
            plan: dict[str, Any] = {}
            try:
                async with httpx.AsyncClient(transport=transport, timeout=35.0, follow_redirects=False) as client:
                    trace_meta = await check_backend(client)
                    record["upstream_catalog"] = trace_meta.get("catalog_trace")
                    file_ref = await ingest_source(client, source)
                    record["source_ref"] = file_ref
                    req = compile_request_from_ref(file_ref["file_id"], file_ref["version"], file_ref["content_hash"])
                    plan = await call(client, "POST", cfg.dcs_url.rstrip("/") + "/v1/plans", cfg.dcs_key, json=req)
                    validate_plan(plan, file_ref)
                    record["plan_hash"] = plan["plan_hash"]
                    record["stages"].append("dcs_ingest_compile_pass")
                    validated = None
                    last_failure = None
                    for attempt in range(1, cfg.max_attempts + 1):
                        record["attempts"] = attempt
                        sys = (
                            "You are a JSON-only extractor. Return exactly one JSON object "
                            'with this shape: {"facts":{"project":"...","deadline":"YYYY-MM-DD"}}. '
                            "Copy values exactly from the source. No markdown, explanation or extra keys."
                        )
                        if attempt > 1:
                            sys += f" Previous attempt failed deterministic gate: {last_failure}. Retry from original SOURCE only."
                        llm_body = {
                            "model": _effective_backend_model(cfg),
                            "messages": [
                                {"role": "system", "content": sys},
                                {"role": "user", "content": source.decode("utf-8")},
                            ],
                            "temperature": 0,
                            "max_tokens": 256,
                            "stream": False,
                        }
                        answer = await complete_backend(client, llm_body)
                        try:
                            content = answer["choices"][0]["message"]["content"]
                            validated = validate_output(content, expected)
                            served = answer.get("model", "")
                            if not _backend_matches(str(served), _effective_backend_model(cfg)):
                                raise POCError(502, "BACKEND_MODEL_MISMATCH", "Gateway returned a different served model")
                            record["served_model"] = served
                            record["stages"].append("validation_pass")
                            break
                        except (KeyError, IndexError, TypeError):
                            last_failure = "INVALID_GATEWAY_RESPONSE"
                        except POCError as ex:
                            last_failure = ex.code
                        record["stages"].append(f"validation_failed:{last_failure}")
                    if validated is None:
                        record["status"] = "FAILED"
                        raise POCError(
                            502, "OUTPUT_VALIDATION_FAILED", "forge-squid output failed deterministic validation; no result committed"
                        )
            except POCError:
                record["status"] = "FAILED"
                record["stages"].append("run_failed")
                raise
            record["status"] = "COMMITTED"
            record["stages"].append("atomic_commit")
            content = json.dumps(validated, ensure_ascii=False, separators=(",", ":"))
            created = int(time.time())
            response_id = "chatcmpl-" + run_id
            response = {
                "id": response_id,
                "object": "chat.completion",
                "created": created,
                "model": _response_model(),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            }
            headers = {"X-Forge-Run-Id": run_id, "X-Forge-Plan-Hash": plan["plan_hash"], "Cache-Control": "no-store"}
            if body.get("stream"):

                def chunk(delta: dict[str, str], finish: str | None = None) -> str:
                    frame = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": _response_model(),
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    }
                    return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

                async def generate():
                    yield chunk({"role": "assistant"})
                    yield chunk({"content": content})
                    yield chunk({}, "stop")
                    yield "data: [DONE]\n\n"

                return StreamingResponse(generate(), media_type="text/event-stream", headers=headers)
            return JSONResponse(content=response, headers=headers)

    return app


app = create_app()
