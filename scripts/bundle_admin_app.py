#!/usr/bin/env python3
"""Concatenate admin app-src fragments into app-bundle.js and footprint app-part*.js slices."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ADMIN = REPO / "fleet_server" / "static" / "admin"
SRC = ADMIN / "app-src"
PART2 = SRC / "part2"
PART3 = SRC / "part3"
PART4 = SRC / "part4"
PART5 = SRC / "part5"
PART6 = SRC / "part6"
MAX_PART_LINES = 650
PART_COUNT = 7
BUNDLE_OUT = ADMIN / "app-bundle.js"

# Part-1 ends before part-2 region (see app-src/part2/MANIFEST.txt).
_PART2_START_MARK = "    function memQuarterFills"
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


def _part3_fragments() -> str:
    return _part_fragments(PART3)


def _part4_fragments() -> str:
    return _part_fragments(PART4)


def _part5_fragments() -> str:
    return _part_fragments(PART5)


def _part6_fragments() -> str:
    return _part_fragments(PART6)


def _trim_part1(text: str) -> str:
    for mark in (
        _PART2_START_MARK,
        "    /* Tile header marks (inline SVG, currentColor from .fleet-tile__brand). */",
        "    function renderCpuCompactTile",
    ):
        idx = text.find(mark)
        if idx >= 0:
            head = text[:idx]
            if not head.endswith("\n"):
                head += "\n"
            return head
    if not text.endswith("\n"):
        text += "\n"
    return text


def build_full_source() -> str:
    p1 = _trim_part1(_read(ADMIN / "app-part1.js"))
    p2 = _part2_fragments()
    p3 = _part3_fragments()
    p4 = _part4_fragments()
    p5 = _part5_fragments()
    p6 = _part6_fragments()
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
    if not full.strip().endswith("})();"):
        print("bundle_admin_app: warning: bundle does not end with IIFE close", file=sys.stderr)
    BUNDLE_OUT.write_text(full, encoding="utf-8")
    parts = split_into_parts(full)
    write_parts(parts)
    line_counts = [len(p.splitlines()) for p in parts]
    print(f"bundle_admin_app: wrote {BUNDLE_OUT.relative_to(REPO)} ({len(full.splitlines())} lines)")
    print(
        "bundle_admin_app: regenerated "
        + ", ".join(f"app-part{i}.js ({n} lines)" for i, n in enumerate(line_counts, start=1))
    )


if __name__ == "__main__":
    main()
