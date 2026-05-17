#!/usr/bin/env python3
"""Structural OpenAPI quality gate for docs/schemas/openapi.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPO / "docs" / "schemas" / "openapi.json"

BINARY_PUTS = {
    ("put", "/v1/jobs/{id}/workspace"),
    ("put", "/v1/container-templates/{id}/package"),
}


def _has_json_schema(content: dict) -> bool:
    mj = content.get("application/json")
    if not isinstance(mj, dict):
        return False
    sch = mj.get("schema")
    return isinstance(sch, dict) and sch


def main() -> int:
    doc = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        print("check-openapi-quality: missing paths", file=sys.stderr)
        return 1
    op_ids: dict[str, str] = {}
    failures = 0
    for pth, bundle in sorted(paths.items()):
        if not isinstance(bundle, dict):
            continue
        declared = {
            seg[1:-1]
            for seg in pth.split("/")
            if seg.startswith("{") and seg.endswith("}")
        }
        for method, op in bundle.items():
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            if not isinstance(op, dict):
                continue
            mlow = method.lower()
            oid = op.get("operationId")
            if not oid or not isinstance(oid, str):
                print(
                    f"check-openapi-quality: {method.upper()} {pth} missing operationId",
                    file=sys.stderr,
                )
                failures += 1
            else:
                if oid in op_ids:
                    print(
                        f"check-openapi-quality: duplicate operationId {oid!r} "
                        f"({op_ids[oid]} vs {method.upper()} {pth})",
                        file=sys.stderr,
                    )
                    failures += 1
                else:
                    op_ids[oid] = f"{method.upper()} {pth}"
            summ = op.get("summary")
            if not summ or not isinstance(summ, str) or len(summ.strip()) < 3:
                print(
                    f"check-openapi-quality: {method.upper()} {pth} summary too weak",
                    file=sys.stderr,
                )
                failures += 1
            desc = op.get("description")
            if not desc or not isinstance(desc, str) or len(desc.strip()) < 20:
                print(
                    f"check-openapi-quality: {method.upper()} {pth} "
                    f"missing or too-short description",
                    file=sys.stderr,
                )
                failures += 1
            params = op.get("parameters") or []
            names = {q.get("name") for q in params if isinstance(q, dict)}
            missing = declared - names
            if missing:
                print(
                    f"check-openapi-quality: {method.upper()} {pth} "
                    f"missing path parameters {sorted(missing)}",
                    file=sys.stderr,
                )
                failures += 1
            if mlow == "post" and pth == "/v1/jobs":
                if "requestBody" not in op:
                    print(
                        "check-openapi-quality: POST /v1/jobs lacks requestBody",
                        file=sys.stderr,
                    )
                    failures += 1
                resp201 = (op.get("responses") or {}).get("201")
                if not isinstance(resp201, dict) or "content" not in resp201:
                    print(
                        "check-openapi-quality: POST /v1/jobs 201 lacks content schema",
                        file=sys.stderr,
                    )
                    failures += 1

            if (mlow, pth) in BINARY_PUTS:
                rb = op.get("requestBody")
                if not isinstance(rb, dict):
                    print(
                        f"check-openapi-quality: {method.upper()} {pth} "
                        f"requires binary requestBody",
                        file=sys.stderr,
                    )
                    failures += 1
                else:
                    content = rb.get("content") or {}
                    if "application/octet-stream" not in content:
                        print(
                            f"check-openapi-quality: {method.upper()} {pth} "
                            f"requestBody must allow application/octet-stream",
                            file=sys.stderr,
                        )
                        failures += 1

            if pth.startswith("/v1/"):
                responses = op.get("responses") or {}
                for code in ("200", "201"):
                    resp = responses.get(code)
                    if not isinstance(resp, dict):
                        continue
                    content = resp.get("content")
                    if not isinstance(content, dict):
                        continue
                    if "application/json" in content and not _has_json_schema(content):
                        print(
                            f"check-openapi-quality: {method.upper()} {pth} {code} "
                            f"application/json missing schema",
                            file=sys.stderr,
                        )
                        failures += 1
                    for ctype in ("text/html", "text/css"):
                        if ctype in content:
                            cobj = content[ctype]
                            if not isinstance(cobj, dict) or "schema" not in cobj:
                                print(
                                    f"check-openapi-quality: {method.upper()} {pth} {code} "
                                    f"{ctype} missing schema",
                                    file=sys.stderr,
                                )
                                failures += 1
                for code, resp in responses.items():
                    if not code.startswith("4") and code not in ("500", "503"):
                        continue
                    if not isinstance(resp, dict):
                        continue
                    content = resp.get("content")
                    if not isinstance(content, dict):
                        print(
                            f"check-openapi-quality: {method.upper()} {pth} {code} "
                            f"missing content block",
                            file=sys.stderr,
                        )
                        failures += 1
                        continue
                    if not _has_json_schema(content):
                        print(
                            f"check-openapi-quality: {method.upper()} {pth} {code} "
                            f"expects application/json ErrorJson",
                            file=sys.stderr,
                        )
                        failures += 1
    if failures:
        print(f"check-openapi-quality: {failures} issue(s)", file=sys.stderr)
        return 1
    print("check-openapi-quality: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
