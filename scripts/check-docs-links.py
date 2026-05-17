#!/usr/bin/env python3
"""Validate relative links in Fleet Markdown point at existing repo files or dirs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

GLOBS = [
    "README.md",
    "CHANGELOG.md",
    "docs/**/*.md",
]

LOCAL_SUFFIXES = (
    ".md",
    ".json",
    ".schema.json",
    ".py",
    ".sh",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".webp",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".html",
    ".css",
    ".env",
    ".example",
)

NO_TRAIL_SLASH_EXT = {".md", ".json", ".py", ".sh", ".png", ".jpg", ".jpeg", ".svg", ".webp"}


def _strip_code_fences(text: str) -> str:
    out: list[str] = []
    fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            out.append(line)
    return "\n".join(out)


def _collect_markdown_files() -> list[Path]:
    files: list[Path] = []
    for pattern in GLOBS:
        if "**" in pattern:
            root_rel = pattern.split("**")[0].rstrip("/")
            files.extend(sorted((REPO / root_rel).rglob("*.md")))
        else:
            p = REPO / pattern
            if p.is_file():
                files.append(p)
    return sorted({p.resolve() for p in files if p.is_file()})


def _href_is_local_filesystem(href: str) -> bool:
    path_part = href.split("#", 1)[0].strip()
    if not path_part:
        return False
    lower = path_part.lower()
    if lower.startswith(("#", "http://", "https://", "mailto:", "ftp://")):
        return False
    if path_part.startswith("//"):
        return False
    return True


def _resolve_target(md_path: Path, href: str) -> Path | None:
    path_part = href.split("#", 1)[0].strip()
    if path_part.startswith("/"):
        return (REPO / path_part.lstrip("/")).resolve()
    return (md_path.parent / path_part).resolve()


def _should_check(target: Path, href_path: str) -> bool:
    """Only check hrefs that look like project-relative assets (not site-only query paths)."""
    p = href_path.split("#", 1)[0].strip()
    if not p or p.startswith("/"):
        # absolute-from-repo-root: always check if file/dir may exist
        return True
    suf = Path(p).suffix.lower()
    if suf in LOCAL_SUFFIXES or suf == ".schema.json":
        return True
    if p.endswith("/"):
        return True
    if "." not in Path(p).name:
        # extensionless rel path — could be directory; check if it exists as dir
        return True
    # *.example without dot in NO_TRAIL — .example is in LOCAL_SUFFIXES
    last = Path(p).name
    if "." not in last:
        return True
    # unknown extension (might be deliberate bare path) — skip
    return False


def _exists(target: Path, href_path: str) -> bool:
    if target.is_file():
        return True
    if target.is_dir():
        return True
    # allow README.md implicit for extensionless directory links
    p = href_path.split("#", 1)[0].rstrip("/")
    if not Path(p).suffix:
        if (target / "README.md").is_file():
            return True
    return False


def main() -> int:
    failures = 0
    for md_path in _collect_markdown_files():
        try:
            raw = md_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"check-docs-links: cannot read {md_path}: {exc}", file=sys.stderr)
            failures += 1
            continue
        body = _strip_code_fences(raw)
        for lineno, line in enumerate(body.splitlines(), start=1):
            for m in LINK_RE.finditer(line):
                href = m.group(2).strip()
                if not _href_is_local_filesystem(href):
                    continue
                path_part = href.split("#", 1)[0].strip()
                if not path_part:
                    continue
                if not _should_check(md_path, path_part):
                    continue
                target = _resolve_target(md_path, href)
                if target is None:
                    continue
                try:
                    target.relative_to(REPO)
                except ValueError:
                    print(
                        f"check-docs-links: escape {target} (from "
                        f"{md_path.relative_to(REPO)}:{lineno} {href!r})",
                        file=sys.stderr,
                    )
                    failures += 1
                    continue
                if not _exists(target, path_part):
                    rel = md_path.relative_to(REPO)
                    print(
                        f"check-docs-links: missing {target} "
                        f"(from {rel}:{lineno} link {href!r})",
                        file=sys.stderr,
                    )
                    failures += 1
    if failures:
        print(f"check-docs-links: {failures} issue(s)", file=sys.stderr)
        return 1
    print("check-docs-links: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
