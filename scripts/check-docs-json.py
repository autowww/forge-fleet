#!/usr/bin/env python3
"""Validate JSON files under docs/schemas plus docs/host-operator-steps.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    paths: list[Path] = sorted((REPO / "docs" / "schemas").glob("*.json"))
    extra = REPO / "docs" / "host-operator-steps.json"
    if extra.is_file():
        paths.append(extra)
    failures = 0
    for p in paths:
        try:
            json.loads(p.read_text(encoding="utf-8"))
            print(f"check-docs-json: OK {p.relative_to(REPO)}")
        except json.JSONDecodeError as exc:
            print(f"check-docs-json: INVALID {p.relative_to(REPO)}: {exc}", file=sys.stderr)
            failures += 1
        except OSError as exc:
            print(f"check-docs-json: READ ERROR {p}: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
