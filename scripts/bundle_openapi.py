#!/usr/bin/env python3
"""Regenerate docs/schemas/openapi.json from docs/schemas/openapi/ fragments."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from split_footprint_modules import bundle_openapi  # noqa: E402


def main() -> int:
    bundle_openapi()
    print("bundle_openapi: wrote docs/schemas/openapi.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
