#!/usr/bin/env python3
"""Fail when scaffold/stub wording leaks into public Fleet docs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Phrases forbidden outside maintainer-only paths (case-insensitive word checks).
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("stub", re.compile(r"\bstub\b", re.I)),
    ("TODO", re.compile(r"\bTODO\b")),
    ("placeholder", re.compile(r"\bplaceholder\b", re.I)),
    ("prompt pack", re.compile(r"prompt\s+pack", re.I)),
]


def _public_md_files() -> list[Path]:
    docs = REPO / "docs"
    out: list[Path] = []
    for p in sorted(docs.rglob("*.md")):
        rel_parts = p.relative_to(docs).parts
        if rel_parts and rel_parts[0] == "maintainers":
            continue
        out.append(p)
    for name in ("README.md", "CHANGELOG.md"):
        root_md = REPO / name
        if root_md.is_file():
            out.append(root_md)
    return sorted({p.resolve() for p in out})


def _strip_fenced_and_html_comments(text: str) -> str:
    out: list[str] = []
    fence = False
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if t.startswith("<!--") and t.endswith("-->"):
            continue
        out.append(line)
    return "\n".join(out)


def main() -> int:
    bad = 0
    for md_path in _public_md_files():
        raw = md_path.read_text(encoding="utf-8")
        body = _strip_fenced_and_html_comments(raw)
        for label, rx in PATTERNS:
            if rx.search(body):
                rel = md_path.relative_to(REPO)
                print(f"check-docs-public-copy: forbidden {label!r} in {rel}", file=sys.stderr)
                bad += 1
    if bad:
        print(f"check-docs-public-copy: {bad} issue(s)", file=sys.stderr)
        return 1
    print("check-docs-public-copy: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
