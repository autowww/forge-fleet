#!/usr/bin/env python3
"""Bump ``version = \"M.m.p\"`` in ``pyproject.toml`` (minor or patch). Prints new version on stdout."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pyproject", type=Path, help="Path to pyproject.toml")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--minor", action="store_true", help="0.2.5 -> 0.3.0")
    g.add_argument("--patch", action="store_true", help="0.2.5 -> 0.2.6")
    args = ap.parse_args()
    path: Path = args.pyproject
    raw = path.read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"\s*$', raw)
    if not m:
        print("bump_pyproject_version: no version = \"M.m.p\" line found", file=sys.stderr)
        sys.exit(1)
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if args.minor:
        new_ver = f"{major}.{minor + 1}.0"
    else:
        new_ver = f"{major}.{minor}.{patch + 1}"
    new_raw, n = re.subn(
        r'(?m)^version\s*=\s*"\d+\.\d+\.\d+"\s*$',
        f'version = "{new_ver}"',
        raw,
        count=1,
    )
    if n != 1:
        print("bump_pyproject_version: replace failed", file=sys.stderr)
        sys.exit(1)
    path.write_text(new_raw, encoding="utf-8")
    print(new_ver)


if __name__ == "__main__":
    main()
