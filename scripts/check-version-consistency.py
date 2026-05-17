#!/usr/bin/env python3
"""Compare package, OpenAPI, and changelog version lines."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise SystemExit("check-version-consistency: pyproject version not found")
    return m.group(1)


def _openapi_version() -> str:
    import json

    p = REPO / "docs" / "schemas" / "openapi.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    v = doc.get("info", {}).get("version")
    if not v:
        raise SystemExit("check-version-consistency: openapi info.version missing")
    return str(v)


def _changelog_head_version() -> str:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## \[([0-9.]+)\]", text, re.M)
    if not m:
        raise SystemExit("check-version-consistency: changelog head not found")
    return m.group(1)


def main() -> int:
    pv = _pyproject_version()
    ov = _openapi_version()
    cv = _changelog_head_version()
    if pv != ov or pv != cv:
        print(
            f"check-version-consistency: mismatch pyproject={pv!r} openapi={ov!r} changelog={cv!r}",
            file=sys.stderr,
        )
        return 1
    print("check-version-consistency: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
