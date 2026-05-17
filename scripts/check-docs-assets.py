#!/usr/bin/env python3
"""Verify local image links in Markdown point at existing files under docs/."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IMG_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
GLOBS = ["docs/**/*.md", "README.md"]

CODE_FENCE = re.compile(r"^```")


def _collect_md() -> list[Path]:
    out: list[Path] = []
    for pattern in GLOBS:
        if "**" in pattern:
            root = pattern.split("**")[0].rstrip("/")
            out.extend((REPO / root).rglob("*.md"))
        else:
            p = REPO / pattern
            if p.is_file():
                out.append(p)
    return sorted({p.resolve() for p in out if p.is_file()})


def _strip_fences(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    fence = False
    for line in lines:
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            out.append(line)
    return "\n".join(out)


def main() -> int:
    bad = 0
    for md in _collect_md():
        raw = md.read_text(encoding="utf-8")
        body = _strip_fences(raw)
        for m in IMG_RE.finditer(body):
            href = m.group(1).strip().split()[0]
            if href.startswith(("http://", "https://", "data:")):
                continue
            path_part = href.split("#", 1)[0]
            if not path_part:
                continue
            if path_part.startswith("/"):
                target = (REPO / path_part.lstrip("/")).resolve()
            else:
                target = (md.parent / path_part).resolve()
            try:
                target.relative_to(REPO)
            except ValueError:
                print(f"check-docs-assets: escape {target} ({md.relative_to(REPO)})", file=sys.stderr)
                bad += 1
                continue
            if not target.is_file():
                print(
                    f"check-docs-assets: missing {target} (from {md.relative_to(REPO)})",
                    file=sys.stderr,
                )
                bad += 1
    if bad:
        print(f"check-docs-assets: {bad} issue(s)", file=sys.stderr)
        return 1
    print("check-docs-assets: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
