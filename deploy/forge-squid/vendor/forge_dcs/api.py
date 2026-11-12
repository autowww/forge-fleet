"""HTTP surface: GET /healthz, GET /v1/capabilities, POST /v1/plans,
POST /v1/sources, GET /v1/sources/{file_id}/versions/{version}[/fragments].

Responses from ``/v1/plans`` and the source routes are canonical bytes, identical to CLI output.

Ingestion envelope (``POST /v1/sources``): the request body **is** the raw file bytes;
``Content-Type`` is the declared MIME (``text/plain``, ``text/markdown``, ``application/json``);
``X-Dcs-File-Id`` is the caller-chosen identifier; optional ``X-Dcs-Tenant-Id`` must equal the
authenticated tenant (403 otherwise). The body is read in chunks and aborted at
``MAX_SOURCE_BYTES + 1`` before any whole-body allocation. ``201`` for a new version, ``200``
when the identical bytes were already registered under that ``file_id`` (idempotent).
The source routes return ``503 STORE_NOT_CONFIGURED`` when ``DCS_STORE_ROOT`` is unset;
``/v1/plans`` then behaves exactly as in P01 (no registry check).
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from forge_dcs import SERVICE_ID, __version__, errors
from forge_dcs.auth import AuthConfig, authenticate, resolve_tenant
from forge_dcs.canonical import NORMALIZATION_VERSION, canonical_bytes
from forge_dcs.compiler import SCHEMA_VERSION, TOKENIZER_UNVERIFIED, compile_plan, load_rulepack
from forge_dcs.contracts import CompileRequest
from forge_dcs.schema_registry import EXECUTION_MANIFEST_ID, NODE_CAPABILITY_ID, PLANIR_ID, PROMPT_ARTIFACT_ID
from forge_dcs.store import ACCEPTED_MIME, MAX_SOURCE_BYTES, STORE_FORMAT, SourceStore, StoreConfig


def _canon(obj: Any, status: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(content=canonical_bytes(obj), status_code=status, media_type="application/json", headers=headers or {})


def create_app(auth_cfg: AuthConfig | None = None, store_cfg: StoreConfig | None = None) -> FastAPI:
    cfg = auth_cfg or AuthConfig.from_env()
    scfg = store_cfg or StoreConfig.from_env()
    app = FastAPI(title="forge-dcs", version=__version__, docs_url=None, redoc_url=None)

    def _store_or_none() -> SourceStore | None:
        return scfg.open() if scfg.root is not None else None

    def _store() -> SourceStore:
        return scfg.open()  # raises STORE_NOT_CONFIGURED (503) when unset

    @app.exception_handler(errors.DcsError)
    async def _dcs_error(_: Request, exc: errors.DcsError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_body())

    @app.exception_handler(RequestValidationError)
    async def _req_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"path": "/" + "/".join(str(p) for p in e.get("loc", [])), "message": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(status_code=422, content=errors.DcsError(errors.REQUEST_INVALID, "request body invalid", 422, details).to_body())

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"ok": True, "service": SERVICE_ID, "version": __version__}

    @app.get("/v1/capabilities")
    async def capabilities(request: Request) -> dict[str, Any]:
        authenticate(request.headers.get("authorization"), cfg)
        rp, rp_digest = load_rulepack()
        return {
            "service": SERVICE_ID,
            "version": __version__,
            "modes": ["STRICT"],
            "determinism_classes": {"STRICT": "available", "PINNED_ML": "not_available", "LLM_EXECUTION": "not_available"},
            "schema_versions": {"planir": SCHEMA_VERSION, "ids": [PLANIR_ID, NODE_CAPABILITY_ID, EXECUTION_MANIFEST_ID, PROMPT_ARTIFACT_ID]},
            "normalization_version": NORMALIZATION_VERSION,
            "tokenizer_profile": TOKENIZER_UNVERIFIED,
            "rule_pack": {"version": rp["rule_pack_version"], "digest": rp_digest, "rules": [r["rule_id"] for r in rp["rules"]]},
            "execution": {"available": False, "phase": "P05"},
            "model_calls_in_compile": False,
            "sources": {
                "configured": scfg.root is not None,
                "store_format": STORE_FORMAT,
                "accepted_mime": list(ACCEPTED_MIME),
                "max_source_bytes": MAX_SOURCE_BYTES,
                "mutations": "none",
            },
        }

    @app.post("/v1/sources")
    async def ingest_source(request: Request) -> Response:
        principal = authenticate(request.headers.get("authorization"), cfg)
        store = _store()
        tenant = resolve_tenant(principal, request.headers.get("x-dcs-tenant-id"))
        file_id = request.headers.get("x-dcs-file-id") or ""
        mime = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_SOURCE_BYTES:
            raise errors.DcsError(errors.SOURCE_TOO_LARGE, f"source exceeds {MAX_SOURCE_BYTES} bytes", http_status=413)
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_SOURCE_BYTES:
                raise errors.DcsError(errors.SOURCE_TOO_LARGE, f"source exceeds {MAX_SOURCE_BYTES} bytes", http_status=413)
            chunks.append(chunk)
        rec, created = store.ingest(tenant, file_id, mime, b"".join(chunks))
        body = rec.to_dict() | {"created": created}
        return _canon(body, 201 if created else 200, {"X-Dcs-Content-Hash": rec.content_hash})

    @app.get("/v1/sources/{file_id}/versions/{version}")
    async def source_version(file_id: str, version: str, request: Request) -> Response:
        principal = authenticate(request.headers.get("authorization"), cfg)
        rec = _store().get_version(principal.tenant_id, file_id, version)
        if rec is None:
            raise errors.DcsError(errors.SOURCE_NOT_FOUND, f"{file_id}@{version} not registered", http_status=404)
        return _canon(rec.to_dict())

    @app.get("/v1/sources/{file_id}/versions/{version}/fragments")
    async def source_fragments(file_id: str, version: str, request: Request) -> Response:
        principal = authenticate(request.headers.get("authorization"), cfg)
        store = _store()
        rec = store.get_version(principal.tenant_id, file_id, version)
        if rec is None:
            raise errors.DcsError(errors.SOURCE_NOT_FOUND, f"{file_id}@{version} not registered", http_status=404)
        frags = [f.to_dict() for f in store.list_fragments(principal.tenant_id, file_id, version)]
        return _canon({"file_id": file_id, "version": version, "content_hash": rec.content_hash, "parser_id": rec.parser_id, "fragments": frags})

    @app.put("/v1/sources/{file_id}/versions/{version}")
    @app.patch("/v1/sources/{file_id}/versions/{version}")
    @app.delete("/v1/sources/{file_id}/versions/{version}")
    async def source_immutable(file_id: str, version: str, request: Request) -> Response:
        authenticate(request.headers.get("authorization"), cfg)
        raise errors.DcsError(errors.SOURCE_IMMUTABLE, "sources are immutable; register a new version instead", http_status=405)

    @app.post("/v1/plans")
    async def plans(request: Request) -> Response:
        principal = authenticate(request.headers.get("authorization"), cfg)
        try:
            payload = json.loads(await request.body() or b"{}")
        except json.JSONDecodeError as exc:
            raise errors.DcsError(errors.REQUEST_INVALID, "body is not valid JSON", 422) from exc
        try:
            req = CompileRequest.model_validate(payload)
        except ValidationError as exc:
            details = [{"path": "/" + "/".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
            raise errors.DcsError(errors.REQUEST_INVALID, "request body invalid", 422, details) from exc
        tenant = resolve_tenant(principal, req.tenant_id)
        plan = compile_plan(req, tenant, _store_or_none())
        return Response(content=canonical_bytes(plan), media_type="application/json", headers={"X-Dcs-Plan-Hash": plan["plan_hash"]})

    return app


app = create_app()
