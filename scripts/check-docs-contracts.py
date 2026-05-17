#!/usr/bin/env python3
"""Fail if fleet_server/main.py exposes HTTP routes not listed in docs/schemas/openapi.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = REPO_ROOT / "fleet_server" / "main.py"
OPENAPI = REPO_ROOT / "docs" / "schemas" / "openapi.json"

VERB_MAP = {"do_GET": "GET", "do_POST": "POST", "do_PUT": "PUT", "do_DELETE": "DELETE"}


def _split_handler_methods(src: str) -> list[tuple[str, str]]:
    """Return [(do_GET, body), ...] for FleetHandler HTTP verbs only."""
    rx = re.compile(r"^    def (do_(?:GET|POST|PUT|DELETE))\(self\) -> None:", re.M)
    matches = list(rx.finditer(src))
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        out.append((name, src[start:end]))
    return out


def _literal_paths(body: str) -> list[str]:
    paths: list[str] = []
    for m in re.finditer(r'(?:if|elif) path == "([^"]+)"', body):
        paths.append(m.group(1))
    return paths


def _regex_patterns(body: str) -> list[str]:
    patterns: list[str] = []
    for m in re.finditer(r're\.match\(r"(\^[^\n"]+\$)"\s*,\s*path\)', body):
        p = m.group(1)
        patterns.append(p)
    for m in re.finditer(r"re\.match\(r'(\^[^\n']+\$)'\s*,\s*path\)", body):
        patterns.append(m.group(1))
    return patterns


def _regex_to_openapi_paths(patt: str) -> list[str]:
    """Map a Python ^...$ regex (path match) to one or more /foo/{param}/bar paths."""
    if not (patt.startswith("^") and patt.endswith("$")):
        return []
    inner = patt[1:-1]

    # Special: workspace worker progress OR complete (single regex → two HTTP routes)
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


def routes_from_main_py() -> set[tuple[str, str]]:
    src = MAIN_PY.read_text(encoding="utf-8")
    found: set[tuple[str, str]] = set()
    for do_name, body in _split_handler_methods(src):
        verb = VERB_MAP[do_name]
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


def main() -> int:
    if not MAIN_PY.is_file():
        print(f"check-docs-contracts: missing {MAIN_PY}", file=sys.stderr)
        return 2
    if not OPENAPI.is_file():
        print(f"check-docs-contracts: missing {OPENAPI}", file=sys.stderr)
        return 2

    code_routes = routes_from_main_py()
    oapi = json.loads(OPENAPI.read_text(encoding="utf-8"))
    spec_routes = routes_from_openapi(oapi)

    missing_in_openapi = sorted(code_routes - spec_routes)
    extra_in_openapi = sorted(spec_routes - code_routes)

    if missing_in_openapi:
        print("check-docs-contracts: routes implemented in fleet_server/main.py but missing from OpenAPI:", file=sys.stderr)
        for verb, path in missing_in_openapi:
            print(f"  {verb} {path}", file=sys.stderr)
        if extra_in_openapi:
            print("check-docs-contracts: (info) OpenAPI-only routes (not in parser output):", file=sys.stderr)
            for verb, path in extra_in_openapi:
                print(f"  {verb} {path}", file=sys.stderr)
        return 1

    if extra_in_openapi:
        print("check-docs-contracts: OpenAPI lists routes not extracted from main.py:", file=sys.stderr)
        for verb, path in extra_in_openapi:
            print(f"  {verb} {path}", file=sys.stderr)
        return 1

    print(f"check-docs-contracts: OK ({len(code_routes)} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
