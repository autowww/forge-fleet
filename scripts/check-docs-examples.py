#!/usr/bin/env python3
"""Validate documented **job create** payloads include schema-required fields.

Scans Markdown (and top-level README) for fenced code blocks that mention
``POST /v1/jobs`` (or ``fleetFetch`` to that path), extracts JSON objects, and
checks ``kind: docker_argv`` plus non-empty string ``argv`` (aligned with
``docs/schemas/job-create-request.schema.json``) without external deps.

Skip a fence by placing ``<!-- docs:skip-job-schema-check -->`` on the closest
previous non-blank line before the opening `` ``` ``.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "docs" / "schemas" / "job-create-request.schema.json"
GLOBS = ["README.md", "docs/**/*.md"]
FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*$")
SKIP_HTML = re.compile(r"<!--\s*docs:skip-job-schema-check\s*-->")


def _collect_md() -> list[Path]:
    out: list[Path] = []
    for pattern in GLOBS:
        if "**" in pattern:
            root = pattern.split("**")[0].rstrip("/")
            out.extend(sorted((REPO / root).rglob("*.md")))
        else:
            p = REPO / pattern
            if p.is_file():
                out.append(p)
    return sorted({p.resolve() for p in out if p.is_file()})


def _strip_bash_hashes(text: str) -> str:
    """Drop full-line # comments and trailing ` # …` (good enough for docs)."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if "#" in line and not _quoted_hash_line(line):
            line = line.split("#", 1)[0].rstrip()
        out.append(line)
    return "\n".join(out)


def _quoted_hash_line(line: str) -> bool:
    """True if first `#` is inside a single-quoted bash string (rough heuristic)."""
    if "#" not in line:
        return False
    parts = line.split("'")
    if len(parts) < 2:
        return False
    first = line.find("#")
    # odd index segments are inside ' ... '
    pos = 0
    for i, seg in enumerate(parts):
        seg_len = len(seg) + (1 if i else 0)
        if i % 2 == 1:
            start = line.find(seg, pos)
            end = start + len(seg)
            if start <= first < end:
                return True
        pos += seg_len
    return False


def _bash_curl_creates_job(body: str) -> bool:
    """True when a line looks like `curl … -X POST …/v1/jobs` with a JSON payload."""
    for line in body.splitlines():
        ul = line.upper()
        if "CURL" not in ul:
            continue
        if "-X POST" not in ul and " POST " not in ul:
            continue
        if "/v1/JOBS" not in line.upper():
            continue
        if "/v1/jobs/" in line.lower() and "/cancel" in line.lower():
            continue
        if not re.search(r"/v1/jobs([\"'`\s]|$)", line.replace("${BASE}", "").replace("${FLEET_BASE_URL}", "")):
            continue
        if "-d" in line or "--data" in line or "--data-binary" in line:
            return True
    return False


def _python_posts_job_create(body: str) -> bool:
    return bool(
        re.search(r'api\s*\(\s*["\']POST["\']\s*,\s*["\']/v1/jobs["\']', body, re.DOTALL)
    )


def _typescript_posts_job_create(body: str) -> bool:
    return bool(
        re.search(r"fleetFetch\s*\(\s*[`'\"]/v1/jobs[`'\"]", body, re.DOTALL)
        and re.search(r"method\s*:\s*[\"']POST[\"']", body, re.I)
    )


def _fence_needs_job_check(body: str) -> bool:
    if "/v1/jobs" not in body:
        return False
    cleaned = _strip_bash_hashes(body)
    if _python_posts_job_create(body):
        return True
    if _typescript_posts_job_create(body):
        return True
    return _bash_curl_creates_job(cleaned)


def _obj_triggers_job_check(obj: dict) -> bool:
    argv = obj.get("argv")
    if not isinstance(argv, list) or not argv:
        return False
    return all(isinstance(x, str) for x in argv)


def _validate_job_obj(obj: dict, *, source: str) -> None:
    kind = obj.get("kind")
    if kind != "docker_argv":
        raise ValueError(f"{source}: job create missing kind 'docker_argv' (got {kind!r})")
    argv = obj.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        raise ValueError(f"{source}: invalid argv for job create")


def _extract_json_objects(text: str) -> list[dict]:
    objs: list[dict] = []
    depth = 0
    start: int | None = None
    for i, c in enumerate(text):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                snippet = text[start : i + 1]
                try:
                    loaded = json.loads(snippet)
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(loaded, dict):
                    objs.append(loaded)
                start = None
    return objs


def _prev_nonblank_skip(lines: list[str], start_idx: int) -> bool:
    j = start_idx - 1
    while j >= 0 and lines[j].strip() == "":
        j -= 1
    return j >= 0 and bool(SKIP_HTML.search(lines[j]))


def _python_api_job_create_dict(body: str) -> dict | None:
    """Parse ``api("POST", "/v1/jobs", { … })`` without tripping over f-string ``{job_id}`` elsewhere."""
    m = re.search(
        r'api\s*\(\s*["\']POST["\']\s*,\s*["\']/v1/jobs["\']\s*,\s*(\{)',
        body,
        re.DOTALL,
    )
    if not m:
        return None
    start = m.start(1)
    depth = 0
    for i in range(start, len(body)):
        c = body[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                snippet = body[start : i + 1]
                try:
                    loaded = ast.literal_eval(snippet)
                except (SyntaxError, ValueError):
                    return None
                return loaded if isinstance(loaded, dict) else None
    return None


def _check_fenced_block(
    md_path: Path,
    body: str,
    fence_idx: int,
    *,
    skip: bool,
) -> list[str]:
    if skip:
        return []
    errs: list[str] = []
    if not _fence_needs_job_check(body):
        return errs
    rel = md_path.relative_to(REPO)
    job_like = [o for o in _extract_json_objects(body) if _obj_triggers_job_check(o)]
    if _python_posts_job_create(body):
        py_job = _python_api_job_create_dict(body)
        if py_job is not None and _obj_triggers_job_check(py_job):
            job_like = [py_job]
    for j, o in enumerate(job_like):
        try:
            _validate_job_obj(o, source=f"{rel} fence#{fence_idx} obj#{j}")
        except ValueError as ex:
            errs.append(str(ex))
    if not job_like:
        if "docker_argv" not in body:
            errs.append(
                f"{rel} fence#{fence_idx}: POST /v1/jobs snippet missing "
                "`kind: docker_argv` (no parseable JSON object with argv[])"
            )
    return errs


def main() -> int:
    if not SCHEMA_PATH.is_file():
        print(f"check-docs-examples: missing {SCHEMA_PATH}", file=sys.stderr)
        return 1
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if set(schema.get("required") or []) != {"kind", "argv"}:
        print("check-docs-examples: job schema required keys changed — update this script", file=sys.stderr)
        return 1

    all_errs: list[str] = []
    for md_path in _collect_md():
        lines = md_path.read_text(encoding="utf-8").splitlines()
        i = 0
        fence_idx = 0
        while i < len(lines):
            if FENCE_RE.match(lines[i]):
                do_skip = _prev_nonblank_skip(lines, i)
                i += 1
                body_lines: list[str] = []
                while i < len(lines) and not FENCE_RE.match(lines[i]):
                    body_lines.append(lines[i] + "\n")
                    i += 1
                body = "".join(body_lines)
                if i < len(lines):
                    i += 1
                all_errs.extend(_check_fenced_block(md_path, body, fence_idx, skip=do_skip))
                fence_idx += 1
                continue
            i += 1

    if all_errs:
        for e in all_errs:
            print(f"check-docs-examples: {e}", file=sys.stderr)
        print(f"check-docs-examples: {len(all_errs)} issue(s)", file=sys.stderr)
        return 1
    print("check-docs-examples: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
