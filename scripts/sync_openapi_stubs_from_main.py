#!/usr/bin/env python3
"""Add minimal OpenAPI path stubs for routes in main.py but missing from openapi.json."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI = REPO_ROOT / "docs" / "schemas" / "openapi.json"

_spec = importlib.util.spec_from_file_location(
    "check_docs_contracts", REPO_ROOT / "scripts" / "check-docs-contracts.py"
)
_cdc = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_cdc)


def _camel_operation_id(verb: str, path: str) -> str:
    parts: list[str] = [verb.lower()]
    for seg in path.strip("/").split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            parts.append("by" + seg[1:-1].title().replace("_", ""))
        else:
            clean = re.sub(r"[^a-zA-Z0-9]+", " ", seg).strip()
            for word in clean.split():
                parts.append(word[:1].lower() + word[1:] if word else "")
    base = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return base[0].lower() + base[1:] if base else "operation"


def _stub_operation(verb: str, path: str, operation_id: str) -> dict:
    op: dict = {
        "tags": ["v1"] if path.startswith("/v1/") else ["admin"],
        "summary": f"{verb} {path}",
        "operationId": operation_id,
        "description": (
            f"{verb} {path}. Operator narrative: "
            "`docs/reference/01-http-api-reference.md`."
        ),
        "responses": {
            "200": {
                "description": "Success payload (see handbook for fields).",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/FleetJsonSuccess"}
                    }
                },
            },
            "401": {
                "description": "Unauthorized.",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorJson"}
                    }
                },
            },
        },
    }
    if path.startswith("/v1/") or path.startswith("/admin/"):
        op["security"] = [{"bearerAuth": []}]
    params = []
    for seg in path.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            name = seg[1:-1]
            params.append(
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )
    if params:
        op["parameters"] = params
    if verb in ("POST", "PUT", "PATCH"):
        op["requestBody"] = {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/FleetJsonSuccess"}
                }
            },
        }
    return op


def main() -> int:
    code_routes = _cdc.routes_from_main_py()
    doc = json.loads(OPENAPI.read_text(encoding="utf-8"))
    spec_routes = _cdc.routes_from_openapi(doc)
    missing = sorted(code_routes - spec_routes)
    if not missing:
        print("sync_openapi_stubs: nothing to add")
        return 0
    paths = doc.setdefault("paths", {})
    schemas = doc.setdefault("components", {}).setdefault("schemas", {})
    if "FleetJsonSuccess" not in schemas:
        schemas["FleetJsonSuccess"] = {
            "type": "object",
            "additionalProperties": True,
        }
    used_ids: set[str] = set()
    for _pth, item in paths.items():
        for _m, op in item.items():
            if isinstance(op, dict) and op.get("operationId"):
                used_ids.add(str(op["operationId"]))
    added = 0
    for verb, path in missing:
        path_item = paths.setdefault(path, {})
        m = verb.lower()
        if m in path_item:
            continue
        oid = _camel_operation_id(verb, path)
        n = 2
        while oid in used_ids:
            oid = f"{_camel_operation_id(verb, path)}{n}"
            n += 1
        used_ids.add(oid)
        path_item[m] = _stub_operation(verb, path, oid)
        added += 1
    doc["info"]["version"] = "0.3.145"
    OPENAPI.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"sync_openapi_stubs: added {added} operation(s) → {OPENAPI.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
