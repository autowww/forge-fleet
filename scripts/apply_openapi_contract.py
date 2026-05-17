#!/usr/bin/env python3
"""Augment docs/schemas/openapi.json with contract fields.

Run from repo root:

    python3 scripts/apply_openapi_contract.py

Idempotent: re-run safe.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPO / "docs" / "schemas" / "openapi.json"
SCHEMA_DIR = REPO / "docs" / "schemas"

OPERATION_IDS: dict[tuple[str, str], str] = {
    ("get", "/admin"): "redirectAdminToSlash",
    ("get", "/admin/"): "getAdminDashboard",
    ("get", "/admin/ks/{path}"): "getAdminKitchensinkAsset",
    ("get", "/admin/static/{path}"): "getAdminPackagedStatic",
    ("get", "/admin/theme.css"): "getAdminThemeCss",
    ("post", "/v1/admin/git-self-update"): "postAdminGitSelfUpdate",
    ("get", "/v1/admin/snapshot"): "getAdminSnapshot",
    ("post", "/v1/admin/test-fleet"): "postAdminTestFleet",
    ("get", "/v1/container-services"): "listContainerServices",
    ("post", "/v1/container-services"): "createContainerService",
    ("get", "/v1/container-services/{id}"): "getContainerService",
    ("put", "/v1/container-services/{id}"): "putContainerService",
    ("delete", "/v1/container-services/{id}"): "deleteContainerService",
    ("post", "/v1/container-services/{id}/start"): "startContainerService",
    ("post", "/v1/container-services/{id}/stop"): "stopContainerService",
    ("get", "/v1/container-templates"): "listContainerTemplates",
    ("put", "/v1/container-templates"): "upsertContainerTemplates",
    ("post", "/v1/container-templates/build"): "buildContainerTemplate",
    ("get", "/v1/container-templates/resolve"): "resolveContainerTemplate",
    ("get", "/v1/container-templates/status"): "getContainerTemplatesStatus",
    ("put", "/v1/container-templates/{id}/package"): "putContainerTemplatePackage",
    ("get", "/v1/container-types"): "listContainerTypes",
    ("post", "/v1/container-types"): "createContainerTypesBatch",
    ("put", "/v1/container-types"): "putContainerTypesBatch",
    ("put", "/v1/container-types/{id}"): "putContainerType",
    ("delete", "/v1/container-types/{id}"): "deleteContainerType",
    ("post", "/v1/containers/dispose"): "disposeContainer",
    ("post", "/v1/cooldown-events"): "createCooldownEvent",
    ("get", "/v1/cooldown-summary"): "getCooldownSummary",
    ("get", "/v1/health"): "getHealth",
    ("post", "/v1/jobs"): "createJob",
    ("get", "/v1/jobs/{id}"): "getJob",
    ("post", "/v1/jobs/{id}/cancel"): "cancelJob",
    ("put", "/v1/jobs/{id}/workspace"): "uploadJobWorkspace",
    ("get", "/v1/jobs/{id}/workspace-worker-bundle"): "getJobWorkspaceWorkerBundle",
    ("post", "/v1/jobs/{id}/workspace-worker-progress"): "postJobWorkspaceWorkerProgress",
    ("post", "/v1/jobs/{id}/workspace-worker-complete"): "completeJobWorkspaceWorker",
    ("get", "/v1/services/forge-llm"): "getForgeLlmServiceLegacy",
    ("post", "/v1/services/forge-llm/start"): "startForgeLlmServiceLegacy",
    ("post", "/v1/services/forge-llm/stop"): "stopForgeLlmServiceLegacy",
    ("get", "/v1/telemetry"): "getTelemetry",
    ("get", "/v1/templates"): "listTemplates",
    ("get", "/v1/version"): "getVersion",
}


def _path_parameters(path: str) -> list[dict]:
    out: list[dict] = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            name = segment[1:-1]
            out.append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": f"Path parameter `{name}`.",
                }
            )
    return out


def _stem_to_component(stem: str) -> str:
    return "".join(part[0].upper() + part[1:] if part else "" for part in stem.split("-"))


def _merge_components(doc: dict) -> None:
    comp = doc.setdefault("components", {})
    schemas = comp.setdefault("schemas", {})
    for p in sorted(SCHEMA_DIR.glob("*.schema.json"), key=lambda x: x.name):
        stem = p.name[: -len(".schema.json")]
        name = _stem_to_component(stem)
        if name not in schemas:
            schemas[name] = {"$ref": p.name}
    if "JobAcceptedResponse" not in schemas:
        schemas["JobAcceptedResponse"] = {
            "type": "object",
            "required": ["ok", "id", "status"],
            "properties": {
                "ok": {"type": "boolean", "const": True},
                "id": {"type": "string"},
                "status": {"type": "string"},
            },
        }


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _json_body_schema(ref_name: str) -> dict:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": _ref(ref_name),
            }
        },
    }


def _json_response(description: str, ref_name: str) -> dict:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ref(ref_name)}},
    }


def _text_response(description: str, content_type: str) -> dict:
    return {
        "description": description,
        "content": {content_type: {"schema": {"type": "string"}}},
    }


def _binary_request_body(description: str) -> dict:
    return {
        "required": True,
        "description": description,
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"},
            },
            "application/gzip": {
                "schema": {"type": "string", "format": "binary"},
            },
        },
    }


def _apply_description(_path: str, _method: str, op: dict) -> None:
    summ = (op.get("summary") or "").strip()
    extra = (
        " Operator narrative, authentication, and curl patterns: "
        "`docs/reference/01-http-api-reference.md`."
    )
    op["description"] = (summ.rstrip(".") + "." + extra) if summ else extra.strip()


def _merge_parameters(op: dict, extra: list[dict]) -> None:
    existing: dict[tuple[str, str], dict] = {}
    for p in op.get("parameters") or []:
        if isinstance(p, dict) and p.get("name") and p.get("in"):
            existing[(str(p["name"]), str(p["in"]))] = p
    for q in extra:
        k = (str(q["name"]), str(q["in"]))
        if k not in existing:
            op.setdefault("parameters", []).append(copy.deepcopy(q))
            existing[k] = q


def _apply_request_bodies(path: str, method: str, op: dict) -> None:
    m = method.lower()
    if m not in ("post", "put", "patch"):
        return
    if path == "/v1/jobs" and m == "post":
        op["requestBody"] = copy.deepcopy(_json_body_schema("JobCreateRequest"))
        return
    if path == "/v1/jobs/{id}/workspace" and m == "put":
        op["requestBody"] = _binary_request_body(
            "Raw bytes of a gzip-compressed tar archive for the job workspace. "
            "The server extracts to a host directory before `docker argv` runs. "
            "Typical clients send `Content-Type: application/octet-stream`."
        )
        return
    if path == "/v1/container-templates/{id}/package" and m == "put":
        op["requestBody"] = _binary_request_body(
            "Tar or tar.gz archive containing a Docker build context (Dockerfile at root or under "
            "one top-level directory). Typical clients send `Content-Type: application/octet-stream`."
        )
        return
    if path == "/v1/cooldown-events" and m == "post":
        op["requestBody"] = copy.deepcopy(_json_body_schema("CooldownEventCreateRequest"))
        return
    if "requestBody" in op:
        return
    if path in (
        "/v1/containers/dispose",
        "/v1/admin/test-fleet",
        "/v1/admin/git-self-update",
        "/v1/container-templates/build",
    ) or path.endswith("/start") or path.endswith("/stop"):
        op.setdefault(
            "requestBody",
            {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "additionalProperties": True},
                    }
                },
            },
        )


def _strip_unauthorized_html(responses: dict) -> None:
    r401 = responses.get("401")
    if isinstance(r401, dict):
        content = r401.get("content")
        if isinstance(content, dict) and "text/html" in content:
            del content["text/html"]
            if not content:
                r401["content"] = {
                    "application/json": {"schema": _ref("ErrorJson")},
                }


def _apply_responses(path: str, method: str, op: dict) -> None:
    m = method.lower()
    responses = op.setdefault("responses", {})
    key = (m, path)

    if path == "/admin" and m == "get":
        responses["302"] = {
            "description": "Redirect to `/admin/`.",
            "headers": {
                "Location": {
                    "schema": {"type": "string"},
                    "example": "/admin/",
                }
            },
        }
    elif path == "/admin/" and m == "get":
        responses["200"] = _text_response(
            "Admin dashboard HTML shell (loads assets under `/admin/ks/`).",
            "text/html",
        )
    elif path == "/admin/theme.css" and m == "get":
        responses["200"] = _text_response(
            "Packaged Forge SDLC minimal theme; 404 if kitchensink checkout is missing in dev.",
            "text/css",
        )
    elif path == "/admin/ks/{path}" and m == "get":
        responses["200"] = {
            "description": (
                "Kitchensink CSS or JavaScript under `kitchensink/css/` or `kitchensink/js/`."
            ),
            "content": {
                "text/css": {"schema": {"type": "string"}},
                "application/javascript": {"schema": {"type": "string"}},
            },
        }
    elif path == "/admin/static/{path}" and m == "get":
        responses["200"] = {
            "description": "Packaged raster/SVG assets (e.g. GPU logos).",
            "content": {
                "image/png": {"schema": {"type": "string", "format": "binary"}},
                "image/webp": {"schema": {"type": "string", "format": "binary"}},
                "image/svg+xml": {"schema": {"type": "string"}},
            },
        }
    elif key == ("get", "/v1/version"):
        responses["200"] = _json_response(
            "Fleet build identity and DB schema version.", "VersionResponse"
        )
    elif key == ("get", "/v1/templates"):
        responses["200"] = _json_response(
            "Embedded template library metadata.", "FleetJsonSuccess"
        )
    elif key == ("get", "/v1/health"):
        responses["200"] = _json_response(
            "Liveness information, auth flag, host snapshot subset.", "HealthResponse"
        )
    elif key == ("get", "/v1/admin/snapshot"):
        responses["200"] = _json_response(
            "Operator snapshot: jobs, host, integrations, recent job rows (paginated).",
            "AdminSnapshotResponse",
        )
    elif key == ("get", "/v1/cooldown-summary"):
        responses["200"] = _json_response(
            "Cooldown aggregates for requested `period` query.", "CooldownSummaryResponse"
        )
    elif key == ("get", "/v1/telemetry"):
        responses["200"] = _json_response(
            "Telemetry samples for requested `period` window.", "TelemetryResponse"
        )
    elif key == ("get", "/v1/container-templates/status"):
        responses["200"] = _json_response(
            "Template build cache and in-process build state.", "ContainerTemplatesStatusResponse"
        )
    elif key == ("get", "/v1/container-templates"):
        responses["200"] = _json_response(
            "Current requirement templates document and paths.", "ContainerTemplatesListResponse"
        )
    elif key == ("get", "/v1/container-templates/resolve"):
        responses["200"] = _json_response(
            "Resolved image / cache state for requested requirement ids.",
            "ContainerTemplatesListResponse",
        )
    elif key == ("get", "/v1/container-types"):
        responses["200"] = _json_response(
            "Container types catalog with materialized rows.", "FleetJsonSuccess"
        )
    elif key == ("get", "/v1/container-services"):
        responses["200"] = _json_response(
            "Managed compose services and path hints.", "ContainerServicesListResponse"
        )
    elif key == ("get", "/v1/container-services/{id}"):
        responses["200"] = _json_response(
            "Single service record plus status.", "FleetJsonSuccess"
        )
    elif key == ("get", "/v1/services/forge-llm"):
        responses["200"] = _json_response(
            "Legacy forge_llm service status mirror.", "FleetJsonSuccess"
        )
    elif key == ("get", "/v1/jobs/{id}"):
        responses["200"] = _json_response(
            "Job record including argv, meta, logs fields when present.", "JobResponse"
        )
    elif key == ("get", "/v1/jobs/{id}/workspace-worker-bundle"):
        responses["200"] = _json_response(
            "Argv bundle for inner workspace worker; requires `X-Workspace-Worker-Token`.",
            "WorkspaceWorkerBundleResponse",
        )
    elif key in (
        ("post", "/v1/jobs/{id}/workspace-worker-progress"),
        ("post", "/v1/jobs/{id}/workspace-worker-complete"),
    ):
        responses["200"] = _json_response(
            "Progress or terminal result stored; minimal ack.", "OkTrue"
        )
    elif key == ("post", "/v1/jobs/{id}/cancel"):
        responses["200"] = _json_response(
            "Cancel request applied (best effort if already terminal).", "JobCancelResponse"
        )
    elif path == "/v1/jobs" and m == "post":
        responses["201"] = {
            "description": "Job accepted and queued (or awaiting workspace upload).",
            "content": {"application/json": {"schema": _ref("JobAcceptedResponse")}},
        }
    elif path == "/v1/jobs/{id}/workspace" and m == "put":
        responses["200"] = _json_response(
            "Workspace extracted; job spawn continues.", "WorkspaceUploadResponse"
        )
    elif path == "/v1/container-templates/{id}/package" and m == "put":
        responses["200"] = _json_response(
            "Template package extracted and requirement row upserted.",
            "TemplatePackageUploadResponse",
        )
    elif m == "post" and path == "/v1/cooldown-events":
        responses["200"] = _json_response(
            "Cooldown event recorded (duration may be clamped).", "OkTrue"
        )
    else:
        generic = (
            isinstance(responses.get("200"), dict)
            and isinstance(responses["200"].get("description"), str)
            and "See forge-fleet docs" in responses["200"]["description"]
            and "content" not in responses["200"]
        )
        if generic:
            responses["200"] = _json_response(
                "Success payload (see handbook for fields).", "FleetJsonSuccess"
            )

    for code, detail in list(responses.items()):
        if not isinstance(detail, dict):
            continue
        if code.startswith("4") or code in ("503", "500"):
            if "content" not in detail:
                detail["content"] = {
                    "application/json": {"schema": _ref("ErrorJson")},
                }
            elif isinstance(detail.get("content"), dict) and "application/json" not in detail["content"]:
                detail["content"]["application/json"] = {"schema": _ref("ErrorJson")}

    _strip_unauthorized_html(responses)


def _apply_extra_parameters(path: str, method: str, op: dict) -> None:
    m = method.lower()
    extra: list[dict] = []
    if path == "/v1/jobs/{id}/workspace" and m == "put":
        extra.append(
            {
                "name": "X-Workspace-Archive-Sha256",
                "in": "header",
                "required": False,
                "schema": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "description": "Optional SHA-256 (hex) of the raw body; mismatch returns 400.",
            }
        )
    if path == "/v1/container-templates/{id}/package" and m == "put":
        extra.append(
            {
                "name": "X-Template-Package-Sha256",
                "in": "header",
                "required": False,
                "schema": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "description": "Optional SHA-256 (hex) of the raw body; mismatch returns 400.",
            }
        )
        extra.extend(
            [
                {
                    "name": "title",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Template title when creating/updating the requirement row.",
                },
                {
                    "name": "notes",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string"},
                    "description": "Optional notes stored on the template row.",
                },
                {
                    "name": "replace",
                    "in": "query",
                    "required": False,
                    "schema": {
                        "type": "string",
                        "enum": ["0", "1", "true", "false", "yes", "no"],
                    },
                    "description": (
                        "When `0`/`false`/`no`, refuse overwrite if template exists. Defaults to replace."
                    ),
                },
            ]
        )
    _merge_parameters(op, extra)


def main() -> None:
    doc = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    _merge_components(doc)

    dup_check: set[str] = set()
    for pth, item in sorted(doc.get("paths", {}).items()):
        for method, op in list(item.items()):
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            if not isinstance(op, dict):
                continue
            key = (method.lower(), pth)
            oid = OPERATION_IDS.get(key)
            if oid is None:
                raise SystemExit(f"missing operationId mapping for {method.upper()} {pth}")
            if oid in dup_check:
                raise SystemExit(f"duplicate operationId {oid}")
            dup_check.add(oid)
            op["operationId"] = oid
            params = _path_parameters(pth)
            existing = {(p.get("name"), p.get("in")): p for p in op.get("parameters") or []}
            for q in params:
                k = (q["name"], q["in"])
                if k not in existing:
                    op.setdefault("parameters", []).append(q)
            _apply_description(pth, method, op)
            _apply_request_bodies(pth, method, op)
            _apply_extra_parameters(pth, method, op)
            _apply_responses(pth, method, op)

    OPENAPI_PATH.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OPENAPI_PATH.relative_to(REPO)}")


if __name__ == "__main__":
    main()
