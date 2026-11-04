"""Isolated, feature-flagged Forge 2B API proof of concept.

NOT a DCS execution engine. Uses forge-dcs ingest + compile, then forge-llm inference.
"""
from __future__ import annotations

import asyncio
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

from . import edgar, graph

log = logging.getLogger("forge_2b")
if not logging.getLogger().handlers:  # uvicorn configures only its own loggers; make node progress visible
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

MODEL_ALIAS = "forge-2b"
SOURCE_FILE_ID = "forge-2b-note"
MAX_BODY_BYTES = 262144
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
    llm_url: str
    llm_key: str
    backend_model: str
    max_attempts: int = 2
    # graph executor knobs
    edgar_user_agent: str = "forge-2b-poc/0.2 (ops@forgesdlc.com)"
    cache_dir: Path | None = None
    max_source_bytes: int = 2 * 1024 * 1024
    window_chars: int = 2000
    max_windows: int = 240
    top_n: int = 80
    llm_timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "Config":
        dcs = _require_http_url("DCS_BASE_URL", os.environ.get("DCS_BASE_URL", "http://127.0.0.1:9793"))
        llm = _require_http_url("FORGE_2B_LLM_BASE_URL", os.environ.get("FORGE_2B_LLM_BASE_URL", ""))
        cache = os.environ.get("FORGE_2B_CACHE_DIR", "")
        return cls(
            enabled=os.environ.get("FORGE_2B_ENABLE_LIVE") == "1",
            incoming_key=os.environ.get("FORGE_2B_API_KEY", ""),
            dcs_url=dcs,
            dcs_key=os.environ.get("DCS_BEARER_TOKEN", os.environ.get("DCS_API_KEY", "")),
            llm_url=llm,
            llm_key=os.environ.get("FORGE_2B_LLM_API_KEY", os.environ.get("LLM_API_KEY", "")),
            backend_model=os.environ.get("FORGE_2B_BACKEND_MODEL_ID", DEFAULT_BACKEND).strip() or DEFAULT_BACKEND,
            edgar_user_agent=os.environ.get("FORGE_2B_EDGAR_USER_AGENT", cls.edgar_user_agent),
            cache_dir=Path(cache) if cache else None,
            window_chars=int(os.environ.get("FORGE_2B_WINDOW_CHARS", cls.window_chars)),
            max_windows=int(os.environ.get("FORGE_2B_MAX_WINDOWS", cls.max_windows)),
            top_n=int(os.environ.get("FORGE_2B_TOP_N", cls.top_n)),
            llm_timeout=float(os.environ.get("FORGE_2B_LLM_TIMEOUT", cls.llm_timeout)),
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
        raise POCError(422, "UNSUPPORTED_INPUT", "First PoC supports only the documented SOURCE/END_SOURCE fixture")
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


def _backend_matches(served: str, expected: str) -> bool:
    if served == expected:
        return True
    if served.endswith(expected) or served.removeprefix("forge-llm.") == expected:
        return True
    return False


def create_app(config: Config | None = None, *, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    cfg = config or Config.from_env()
    app = FastAPI(title="Forge 2B OpenAI API PoC", docs_url=None, redoc_url=None)
    traces: dict[str, dict[str, Any]] = {}
    run_sem = asyncio.Semaphore(1)

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
        if not all([cfg.dcs_url, cfg.dcs_key, cfg.llm_url, cfg.llm_key, cfg.backend_model]):
            raise POCError(503, "UPSTREAM_NOT_CONFIGURED", "Upstream DCS or forge-llm config incomplete")

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
        models = await call(client, "GET", cfg.llm_url.rstrip("/") + "/models", cfg.llm_key)
        ids = {row.get("id") for row in models.get("data", []) if isinstance(row, dict)}
        if cfg.backend_model not in ids:
            raise POCError(503, "BACKEND_MODEL_NOT_ADVERTISED", "Backend model not advertised by authorized forge-llm gateway")
        catalog_trace: dict[str, Any] = {}
        try:
            catalog_trace = await call(client, "GET", cfg.llm_url.rstrip("/") + "/llm/catalog", cfg.llm_key)
        except POCError:
            catalog_trace = {"note": "catalog optional for gate; models list passed"}
        return {"capabilities": caps, "catalog_trace": catalog_trace}

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
        return {"ok": True, "service": "forge-2b-poc", "live_enabled": cfg.enabled}

    @app.get("/v1/models")
    async def models(request: Request) -> dict[str, Any]:
        require_access(request)
        require_live()
        async with httpx.AsyncClient(transport=transport, timeout=12.0, follow_redirects=False) as client:
            await check_backend(client)
        return {"object": "list", "data": [{"id": MODEL_ALIAS, "object": "model", "created": 0, "owned_by": "forge-2b-poc"}]}

    @app.get("/v1/forge/runs/{run_id}")
    async def run_trace(run_id: str, request: Request) -> dict[str, Any]:
        require_access(request)
        if run_id not in traces:
            raise POCError(404, "RUN_NOT_FOUND", "No such run in this PoC process")
        return dict(traces[run_id])

    async def graph_run(request: Request, body: dict[str, Any], user_text: str):
        """10-K directive -> forge-dcs plan -> windowed atomic Q2 decisions -> deterministic reduce."""
        directive = edgar.parse_directive(user_text)
        assert directive is not None
        ticker, accession = directive
        run_id = uuid.uuid4().hex
        created = int(time.time())
        response_id = "chatcmpl-" + run_id
        stream = bool(body.get("stream"))

        def chunk(delta: dict[str, str], finish: str | None = None) -> str:
            frame = {
                "id": response_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": MODEL_ALIAS,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            return "data: " + json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n\n"

        record: dict[str, Any] = {
            "run_id": run_id,
            "kind": "graph",
            "model_alias": MODEL_ALIAS,
            "backend_model": cfg.backend_model,
            "raw_prompt_sha256": hashlib.sha256(user_text.encode()).hexdigest(),
            "directive": {"ticker": ticker, "accession": accession},
            "status": "RUNNING",
            "stages": ["accepted"],
            "windows": [],
            "result": [],
        }
        if len(traces) >= 100:
            traces.pop(next(iter(traces)))
        traces[run_id] = record

        async def body_gen():
            """Yields markdown text pieces; raises POCError on run failure (before any text when possible)."""
            async with run_sem:
                async with httpx.AsyncClient(transport=transport, timeout=cfg.llm_timeout, follow_redirects=False) as client:
                    trace_meta = await check_backend(client)
                    record["upstream_catalog"] = trace_meta.get("catalog_trace")
                    try:
                        ref = await edgar.resolve_filing(client, ticker, accession, user_agent=cfg.edgar_user_agent)
                        data = await edgar.fetch_filing_text(client, ref, user_agent=cfg.edgar_user_agent, cache_dir=cfg.cache_dir)
                    except edgar.EdgarError as ex:
                        raise POCError(502, ex.code, ex.message) from ex
                    if len(data) > cfg.max_source_bytes:
                        raise POCError(413, "SOURCE_TOO_LARGE", "Filing text exceeds DCS source cap")
                    record["source"] = edgar.filing_meta(ref, data)
                    record["stages"].append("edgar_resolved")
                    file_ref = await ingest_source(client, data, ref.file_id)
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
                    yield graph.render_markdown_header(run_id, plan["plan_hash"], file_ref, counts, len(windows), threshold)

                    async def llm(msgs: list[dict[str, str]], max_tokens: int) -> tuple[str, str]:
                        answer = await call(
                            client,
                            "POST",
                            cfg.llm_url.rstrip("/") + "/chat/completions",
                            cfg.llm_key,
                            json={"model": cfg.backend_model, "messages": msgs, "temperature": 0, "max_tokens": max_tokens, "stream": False},
                        )
                        served = str(answer.get("model", ""))
                        if not _backend_matches(served, cfg.backend_model):
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
                    committed = [w for w in windows if w.status == "COMMITTED"]
                    if not committed:
                        record["status"] = "FAILED"
                        raise POCError(502, "OUTPUT_VALIDATION_FAILED", "No window node committed; no result")
                    result = graph.reduce_statements(windows, top_n=cfg.top_n)
                    record["result"] = result
                    record["status"] = "COMMITTED"
                    record["stages"] += ["reduce_pass", "atomic_commit"]
                    yield graph.render_result_markdown(result, windows, run_id)
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
                    "model": MODEL_ALIAS,
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
                yield chunk({"content": f"\n\n**Run failed:** `{ex.code}` — {ex.message}. No result committed.\n"})
            yield chunk({}, "stop")
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Forge-Run-Id": run_id, "Cache-Control": "no-store"},
        )

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
        if not isinstance(body, dict) or body.get("model") != MODEL_ALIAS:
            raise POCError(404, "MODEL_NOT_FOUND", "Unknown PoC model")
        messages = body.get("messages")
        user_text = _last_user_text(messages)
        if user_text is None:
            raise POCError(422, "UNSUPPORTED_CHAT", "PoC accepts plain-text user messages only")
        if body.get("tools") or body.get("tool_choice") or body.get("response_format"):
            raise POCError(422, "UNSUPPORTED_FEATURE", "Tools and client-supplied output schemas are outside first PoC")
        if body.get("stream") not in (None, True, False):
            raise POCError(422, "INVALID_REQUEST", "stream must be boolean")
        if edgar.parse_directive(user_text) and "SOURCE:" not in user_text:
            return await graph_run(request, body, user_text)
        expected, source = parse_fixture(user_text)
        run_id = uuid.uuid4().hex

        async with run_sem:
            record: dict[str, Any] = {
                "run_id": run_id,
                "model_alias": MODEL_ALIAS,
                "backend_model": cfg.backend_model,
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
                            "model": cfg.backend_model,
                            "messages": [
                                {"role": "system", "content": sys},
                                {"role": "user", "content": source.decode("utf-8")},
                            ],
                            "temperature": 0,
                            "max_tokens": 256,
                            "stream": False,
                        }
                        answer = await call(
                            client, "POST", cfg.llm_url.rstrip("/") + "/chat/completions", cfg.llm_key, json=llm_body
                        )
                        try:
                            content = answer["choices"][0]["message"]["content"]
                            validated = validate_output(content, expected)
                            served = answer.get("model", "")
                            if not _backend_matches(str(served), cfg.backend_model):
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
                            502, "OUTPUT_VALIDATION_FAILED", "Forge 2B output failed deterministic validation; no result committed"
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
                "model": MODEL_ALIAS,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            }
            headers = {"X-Forge-Run-Id": run_id, "X-Forge-Plan-Hash": plan["plan_hash"], "Cache-Control": "no-store"}
            if body.get("stream"):

                def chunk(delta: dict[str, str], finish: str | None = None) -> str:
                    frame = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": MODEL_ALIAS,
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
