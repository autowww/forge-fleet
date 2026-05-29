#!/usr/bin/env python3
"""Fail if fleet_server HTTP routes are not listed in docs/schemas/openapi.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO_ROOT / "fleet_server" / "http" / "routes"
OPENAPI_FRAGMENTS = REPO_ROOT / "docs" / "schemas" / "openapi"
OPENAPI = REPO_ROOT / "docs" / "schemas" / "openapi.json"

VERB_MAP = {
    "get.py": "GET",
    "post.py": "POST",
    "put.py": "PUT",
    "delete.py": "DELETE",
}


def _split_handler_method(src: str, do_name: str) -> str:
    rx = re.compile(rf"^    def {re.escape(do_name)}\(self\) -> None:", re.M)
    m = rx.search(src)
    if not m:
        return ""
    start = m.end()
    nxt = re.compile(r"^    def ", re.M)
    m2 = nxt.search(src, start)
    end = m2.start() if m2 else len(src)
    return src[start:end]


def _literal_paths(body: str) -> list[str]:
    paths: list[str] = []
    for m in re.finditer(r'(?:if|elif) path == "([^"]+)"', body):
        paths.append(m.group(1))
    return paths


def _regex_patterns(body: str) -> list[str]:
    patterns: list[str] = []
    for m in re.finditer(r're\.match\(r"(\^[^\n"]+\$)"\s*,\s*path\)', body):
        patterns.append(m.group(1))
    for m in re.finditer(r"re\.match\(r'(\^[^\n']+\$)'\s*,\s*path\)", body):
        patterns.append(m.group(1))
    return patterns


def _regex_to_openapi_paths(patt: str) -> list[str]:
    """Map a Python ^...$ regex (path match) to one or more /foo/{param}/bar paths."""
    if not (patt.startswith("^") and patt.endswith("$")):
        return []
    inner = patt[1:-1]

    if "workspace-worker-(progress|complete)" in inner:
        return [
            "/v1/jobs/{id}/workspace-worker-progress",
            "/v1/jobs/{id}/workspace-worker-complete",
        ]

    s = inner
    while "([^/]+)" in s:
        s = s.replace("([^/]+)", "{id}", 1)
    while "(.+)" in s:
        s = s.replace("(.+)", "{path}", 1)

    if "(" in s or ")" in s:
        raise ValueError(f"Unnormalized route regex: {patt!r}")

    if not s.startswith("/"):
        s = "/" + s
    return [s]


def routes_from_http_routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    do_by_file = {
        "get.py": "do_GET",
        "post.py": "do_POST",
        "put.py": "do_PUT",
        "delete.py": "do_DELETE",
    }
    for fname, do_name in do_by_file.items():
        path = ROUTES_DIR / fname
        if not path.is_file():
            continue
        src = path.read_text(encoding="utf-8")
        body = _split_handler_method(src, do_name)
        verb = VERB_MAP[fname]
        for p in _literal_paths(body):
            found.add((verb, p))
        for rx in _regex_patterns(body):
            for op in _regex_to_openapi_paths(rx):
                found.add((verb, op))
    return found


def routes_from_openapi(doc: dict) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return out
    for path_key, item in paths.items():
        if not isinstance(item, dict):
            continue
        for method in ("get", "post", "put", "delete", "patch", "options", "head"):
            if method not in item:
                continue
            out.add((method.upper(), path_key))
    return out


def _load_openapi() -> dict:
    if (OPENAPI_FRAGMENTS / "openapi-root.json").is_file():
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from openapi_fragments import load_openapi_doc

        return load_openapi_doc()
    if OPENAPI.is_file():
        return json.loads(OPENAPI.read_text(encoding="utf-8"))
    raise FileNotFoundError(
        "check-docs-contracts: missing OpenAPI fragments or docs/schemas/openapi.json"
    )


def main() -> int:
    if not ROUTES_DIR.is_dir():
        print(f"check-docs-contracts: missing {ROUTES_DIR}", file=sys.stderr)
        return 2
    try:
        oapi = _load_openapi()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    code_routes = routes_from_http_routes()
    spec_routes = routes_from_openapi(oapi)

    missing_in_openapi = sorted(code_routes - spec_routes)
    extra_in_openapi = sorted(spec_routes - code_routes)

    if missing_in_openapi:
        print(
            "check-docs-contracts: routes in fleet_server/http/routes but missing from OpenAPI:",
            file=sys.stderr,
        )
        for verb, path in missing_in_openapi:
            print(f"  {verb} {path}", file=sys.stderr)
        if extra_in_openapi:
            print("check-docs-contracts: (info) OpenAPI-only routes:", file=sys.stderr)
            for verb, path in extra_in_openapi:
                print(f"  {verb} {path}", file=sys.stderr)
        return 1

    if extra_in_openapi:
        print("check-docs-contracts: OpenAPI lists routes not in http/routes:", file=sys.stderr)
        for verb, path in extra_in_openapi:
            print(f"  {verb} {path}", file=sys.stderr)
        return 1

    print(f"check-docs-contracts: OK ({len(code_routes)} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
