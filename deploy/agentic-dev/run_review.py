#!/usr/bin/env python3
"""Independent code review of an agent PR, start to merge decision. Runs inside forge_agentic_dev.

Separate container, separate clone, no Cursor key. Reads a ``forge.code_review_task.v1`` envelope,
re-verifies the pushed ``head_sha`` on its own checkout, runs deterministic checks, emits
``forge.review_result.v1`` and — only on ``verdict: pass`` with no critical finding, or with an
operator-approved ``merge_override`` bound to this exact head — squash-merges via the GitHub API.

The LLM step is advisory and never sets ``critical`` on its own.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from pathlib import Path
from typing import Any

from run_task import Recorder, github_json, path_guard, secret_scan

LOCKFILES = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum", "composer.lock", "uv.lock")
PROTECTED = (".github/**", "deploy/**", "Dockerfile*", "**/Dockerfile*", "**/*.service", "**/compose*.y*ml", "**/*.pem", "**/*.key", "**/*.env", "**/secrets*")
LARGE_CHANGE_LINES = 1500
SCHEMA = "forge.review_result.v1"


def _check(checks: list[dict[str, Any]], cid: str, status: str, detail: str = "") -> None:
    checks.append({"id": cid, "status": status, "detail": detail[:400]})


def deterministic_checks(*, changed: list[str], allow: list[str], deny: list[str], secret_hits: list[str], conflict: bool,
                         diff_lines: int, trailer_ok: bool, head_matches: bool) -> list[dict[str, Any]]:
    """Pure: status ∈ pass | fail | critical. ``fail`` blocks; ``critical`` needs forgeadmin release."""
    checks: list[dict[str, Any]] = []
    _check(checks, "head_pinned", "pass" if head_matches else "fail", "" if head_matches else "branch tip moved since READY FOR TEST")
    bad = path_guard(changed, allow, deny)
    _check(checks, "path_guard", "pass" if not bad else "fail", ", ".join(bad[:10]))
    _check(checks, "secret_scan", "pass" if not secret_hits else "fail", ", ".join(secret_hits[:10]))
    _check(checks, "task_trailer", "pass" if trailer_ok else "fail", "" if trailer_ok else "missing Forge-Task trailer on agent commit")
    locks = [p for p in changed if Path(p).name in LOCKFILES]
    _check(checks, "lockfile_diff", "critical" if locks else "pass", ", ".join(locks[:10]))
    prot = [p for p in changed if any(fnmatch.fnmatch(p, pat) for pat in PROTECTED)]
    _check(checks, "protected_paths", "critical" if prot else "pass", ", ".join(prot[:10]))
    _check(checks, "conflict_probe", "critical" if conflict else "pass", "does not merge cleanly into current base" if conflict else "")
    _check(checks, "change_size", "critical" if diff_lines > LARGE_CHANGE_LINES else "pass", f"{diff_lines} changed lines")
    return checks


def verdict_for(checks: list[dict[str, Any]], verify_ok: bool) -> tuple[str, bool]:
    if not verify_ok or any(c["status"] == "fail" for c in checks):
        return "fail", any(c["status"] == "critical" for c in checks)
    if any(c["status"] == "critical" for c in checks):
        return "hold", True
    return "pass", False


def review_main(task: dict[str, Any], out_dir: Path, rec: Recorder) -> dict[str, Any]:
    repo = str(task.get("repo") or "")
    branch = str(task.get("branch") or "")
    base_ref = str(task.get("base_ref") or "main")
    head = str(task.get("head_sha") or "")
    pr = task.get("pr_number")
    task_id = str(task.get("task_id") or "")
    result: dict[str, Any] = {
        "schema": SCHEMA, "task_id": task_id, "repo": repo, "pr_number": pr, "pr_url": None, "branch": branch,
        "base_sha": None, "head_sha": head, "independent_verify": {"sha": head, "commands": [], "exit_codes": []},
        "checks": [], "llm_findings": [], "critical": False, "verdict": "fail", "merged": False, "merge_sha": None,
        "merge_error": None, "required_checks_blocking": [], "status": "failed", "hold_reason": None,
    }
    token = os.environ.get("GIT_TOKEN") or ""
    if not token:
        result["hold_reason"] = "credentials_missing"
        result["status"] = "hold"
        return result
    if not re.match(r"^[0-9a-f]{40}$", head) or not isinstance(pr, int):
        result["hold_reason"] = "invalid_review_target"
        return result

    work = Path(os.environ.get("WORK_DIR") or (Path.home() / "work"))
    work.mkdir(parents=True, exist_ok=True)
    checkout = work / "review"
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "forge-reviewer", "GIT_AUTHOR_EMAIL": "reviewer@forgesdlc.com",
                "GIT_COMMITTER_NAME": "forge-reviewer", "GIT_COMMITTER_EMAIL": "reviewer@forgesdlc.com"})
    helper = work / "git-askpass.sh"
    helper.write_text("#!/bin/sh\ncase \"$1\" in *sername*) echo x-access-token;; *) echo \"$GIT_TOKEN\";; esac\n", encoding="utf-8")
    helper.chmod(0o700)
    env["GIT_ASKPASS"] = str(helper)
    remote = f"https://github.com/{repo}.git"

    if rec.run("clone", ["git", "clone", "--branch", base_ref, remote, str(checkout)], cwd=work, env=env, timeout=600).returncode != 0:
        result["hold_reason"] = "clone_failed"
        return result
    result["base_sha"] = rec.run("base_sha", ["git", "rev-parse", "HEAD"], cwd=checkout, env=env).stdout.strip() or None
    if rec.run("fetch_branch", ["git", "fetch", "-q", "origin", branch], cwd=checkout, env=env, timeout=300).returncode != 0:
        result["hold_reason"] = "branch_missing"
        return result
    tip = rec.run("branch_tip", ["git", "rev-parse", "FETCH_HEAD"], cwd=checkout, env=env).stdout.strip()
    head_matches = tip == head
    if rec.run("checkout_head", ["git", "checkout", "-q", "--detach", head], cwd=checkout, env=env).returncode != 0:
        result["hold_reason"] = "head_unreachable"
        return result
    base_point = rec.run("merge_base", ["git", "merge-base", f"origin/{base_ref}", head], cwd=checkout, env=env).stdout.strip()
    changed = [l.strip() for l in rec.run("changed", ["git", "diff", "--name-only", f"{base_point}..{head}"], cwd=checkout, env=env).stdout.splitlines() if l.strip()]
    result["changed_files"] = changed
    stat = rec.run("diffstat", ["git", "diff", "--shortstat", f"{base_point}..{head}"], cwd=checkout, env=env).stdout
    nums = [int(n) for n in re.findall(r"(\d+) (?:insertion|deletion)", stat)]
    diff_lines = sum(nums)
    trailer = rec.run("trailer", ["git", "log", "-1", "--format=%(trailers:key=Forge-Task,valueonly)", head], cwd=checkout, env=env).stdout.strip()
    trailer_ok = trailer == task_id
    conflict = rec.run("conflict_probe", ["git", "merge-tree", "--write-tree", f"origin/{base_ref}", head], cwd=checkout, env=env).returncode != 0

    checks = deterministic_checks(changed=changed, allow=list(task.get("allow_paths") or ["**"]), deny=list(task.get("deny_paths") or []),
                                  secret_hits=secret_scan(checkout, changed), conflict=conflict, diff_lines=diff_lines,
                                  trailer_ok=trailer_ok, head_matches=head_matches)
    result["checks"] = checks

    verify_ok = True
    for cmd in [str(c) for c in (task.get("verify") or [])][:8]:
        proc = rec.run("verify", ["bash", "-lc", cmd], cwd=checkout, env=env, timeout=int(task.get("verify_timeout_s") or 900))
        result["independent_verify"]["commands"].append(cmd)
        result["independent_verify"]["exit_codes"].append(proc.returncode)
        verify_ok = verify_ok and proc.returncode == 0
    if not verify_ok:
        _check(checks, "independent_verify", "fail", "a verify command failed on the reviewer's checkout")

    verdict, critical = verdict_for(checks, verify_ok)
    result["verdict"], result["critical"] = verdict, critical
    rec.note("verdict", verdict=verdict, critical=critical, checks=[(c["id"], c["status"]) for c in checks])

    override = task.get("merge_override") if isinstance(task.get("merge_override"), dict) else None
    may_merge = (verdict == "pass" and not critical) or (override is not None and verdict != "fail" and head_matches)
    if override is not None and verdict == "fail":
        result["hold_reason"] = "override_refused_on_fail"
    if may_merge:
        title = f"{str(task.get('goal') or 'agent task')[:80].strip()} (Forge-Task {task_id})"
        body = {"merge_method": "squash", "sha": head, "commit_title": title[:200],
                "commit_message": f"Forge-Task: {task_id}\nReviewed-By: forge-reviewer\n" + (f"Merge-Approval: {override.get('event_id')}\n" if override else "")}
        code, resp = github_json("PUT", f"https://api.github.com/repos/{repo}/pulls/{pr}/merge", token, body)
        rec.note("merge", http=code, merged=bool(resp.get("merged")))
        if code == 200 and resp.get("merged"):
            result["merged"] = True
            result["merge_sha"] = resp.get("sha")
            code2, _ = github_json("DELETE", f"https://api.github.com/repos/{repo}/git/refs/heads/{branch}", token)
            rec.note("delete_branch", http=code2)
        else:
            msg = str(resp.get("message") or code)
            result["merge_error"] = msg[:300]
            result["required_checks_blocking"] = re.findall(r"Required status check \"([^\"]+)\"", msg) or ([ "required_checks" ] if "status check" in msg.lower() else [])
    result["status"] = {"pass": "pass", "hold": "hold"}.get(verdict, "failed")
    if verdict == "fail" and not result.get("hold_reason"):
        result["hold_reason"] = "review_fail:" + ",".join(c["id"] for c in checks if c["status"] == "fail")
    return result
