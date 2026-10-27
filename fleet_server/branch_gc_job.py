"""Delete expired ``agent/*`` branches (no open PR, older than TTL). GitHub API only."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from fleet_server import agentic_dev_job

_API = "https://api.github.com"


def ttl_days() -> int:
    try:
        return max(1, int(os.environ.get("FLEET_AGENTIC_BRANCH_TTL_DAYS") or 14))
    except ValueError:
        return 14


def _gh(method: str, path: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(_API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "forge-fleet-branch-gc")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None


def _repos_from(body: dict[str, Any]) -> list[str]:
    repos = body.get("repos")
    if isinstance(repos, list):
        out = [str(r) for r in repos if isinstance(r, str) and agentic_dev_job._REPO_RE.match(r) and agentic_dev_job.repo_allowed(r)]
        return out
    raw = str(os.environ.get("FLEET_AGENTIC_GC_REPOS") or "").strip()
    return [r.strip() for r in raw.split(",") if r.strip() and agentic_dev_job.repo_allowed(r.strip())]


def collect_expired(repo: str, token: str, *, now: datetime | None = None, fetch=_gh) -> list[dict[str, Any]]:
    """Agent-lane branches with no open PR and last commit older than TTL."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=ttl_days())
    code, branches = fetch("GET", f"/repos/{repo}/branches?per_page=100", token)
    if code != 200 or not isinstance(branches, list):
        return []
    code, pulls = fetch("GET", f"/repos/{repo}/pulls?state=open&per_page=100", token)
    open_heads = {str(p.get("head", {}).get("ref")) for p in (pulls or []) if isinstance(p, dict)} if code == 200 else set()
    expired: list[dict[str, Any]] = []
    for b in branches:
        name = str(b.get("name") or "")
        if not name.startswith("agent/") or name in open_heads:
            continue
        sha = str((b.get("commit") or {}).get("sha") or "")
        code, commit = fetch("GET", f"/repos/{repo}/commits/{sha}", token)
        if code != 200 or not isinstance(commit, dict):
            continue
        date_raw = str(((commit.get("commit") or {}).get("committer") or {}).get("date") or "")
        try:
            when = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            expired.append({"repo": repo, "branch": name, "sha": sha, "last_commit": date_raw})
    return expired


def run(body: object, *, fetch=_gh) -> dict[str, Any]:
    body = body if isinstance(body, dict) else {}
    token = agentic_dev_job.git_token()
    if not token:
        return {"http": 400, "ok": False, "error": "git_token_not_configured"}
    dry_run = bool(body.get("dry_run", True))
    repos = _repos_from(body)
    if not repos:
        return {"http": 400, "ok": False, "error": "no_repos"}
    deleted: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for repo in repos:
        for row in collect_expired(repo, token, fetch=fetch):
            candidates.append(row)
            if dry_run:
                continue
            ref = urllib.parse.quote(f"heads/{row['branch']}", safe="/")
            code, _ = fetch("DELETE", f"/repos/{repo}/git/refs/{ref}", token)
            row = dict(row, deleted=code in (204, 200))
            deleted.append(row)
    return {"http": 200, "ok": True, "dry_run": dry_run, "ttl_days": ttl_days(), "candidates": candidates, "deleted": deleted}
