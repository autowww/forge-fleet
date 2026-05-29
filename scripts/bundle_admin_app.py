#!/usr/bin/env python3
"""Concatenate admin app-src fragments and regenerate app-part*.js (valid IIFE)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADMIN = REPO / "fleet_server" / "static" / "admin"
SRC = ADMIN / "app-src"
PART2 = SRC / "part2"
PART4 = SRC / "part4"
MAX_PART_LINES = 650
PART_COUNT = 6

_PART2_START_MARK = "    function renderCpuCompactTile"
_PART3_RESUME_MARK = "    /** UTC x-axis ticks and labels below the plot"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _part_fragments(manifest_dir: Path) -> str:
    manifest = manifest_dir / "MANIFEST.txt"
    names: list[str] = []
    for line in _read(manifest).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line)
    chunks: list[str] = []
    for name in names:
        frag = manifest_dir / name
        if not frag.is_file():
            raise SystemExit(f"bundle_admin_app: missing fragment {frag}")
        text = _read(frag)
        if not text.endswith("\n"):
            text += "\n"
        chunks.append(text)
    return "".join(chunks)


def _part2_fragments() -> str:
    return _part_fragments(PART2)


def _part4_fragments() -> str:
    return _part_fragments(PART4)


def _trim_part1(text: str) -> str:
    idx = text.find(_PART2_START_MARK)
    if idx < 0:
        # Already trimmed — part-2 region lives in app-src/part2 fragments.
        if not text.endswith("\n"):
            text += "\n"
        return text
    head = text[:idx]
    if not head.endswith("\n"):
        head += "\n"
    return head


def _trim_part3(text: str) -> str:
    idx = text.find(_PART3_RESUME_MARK)
    if idx < 0:
        raise SystemExit("bundle_admin_app: part3 resume marker not found in app-part3.js")
    return text[idx:]


def build_full_source() -> str:
    p1 = _trim_part1(_read(ADMIN / "app-part1.js"))
    p2 = _part2_fragments()
    p3 = _trim_part3(_read(ADMIN / "app-part3.js"))
    p4 = _part4_fragments()
    p5 = _read(ADMIN / "app-part5.js")
    p6 = _read(ADMIN / "app-part6.js")
    return p1 + p2 + p3 + p4 + p5 + p6


def split_into_parts(text: str, max_lines: int = MAX_PART_LINES) -> list[str]:
    lines = text.splitlines(keepends=True)
    parts: list[str] = []
    chunk: list[str] = []
    for line in lines:
        chunk.append(line)
        if len(chunk) >= max_lines:
            parts.append("".join(chunk))
            chunk = []
    if chunk:
        parts.append("".join(chunk))
    return parts


def write_parts(parts: list[str]) -> None:
    if len(parts) != PART_COUNT:
        print(
            f"bundle_admin_app: wrote {len(parts)} parts (expected {PART_COUNT}); "
            "update PART_COUNT in bundle_admin_app.py and fleet_server/http/base.py if intentional.",
            file=sys.stderr,
        )
    for i, body in enumerate(parts, start=1):
        out = ADMIN / f"app-part{i}.js"
        out.write_text(body, encoding="utf-8")
    for stale in ADMIN.glob("app-part*.js"):
        m = re.match(r"^app-part(\d+)\.js$", stale.name, re.I)
        if m and int(m.group(1)) > len(parts):
            stale.unlink()


def main() -> None:
    full = build_full_source()
    parts = split_into_parts(full)
    write_parts(parts)
    line_counts = [len(p.splitlines()) for p in parts]
    print(
        "bundle_admin_app: regenerated "
        + ", ".join(f"app-part{i}.js ({n} lines)" for i, n in enumerate(line_counts, start=1))
    )


if __name__ == "__main__":
    main()
