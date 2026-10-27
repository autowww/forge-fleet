#!/usr/bin/env python3
"""One approved repo task, start to pushed branch. Runs inside forge_agentic_dev.

Contract (also honored when run on a host for tests):
  TASK_FILE   (default /task/task.json)  -> forge.agentic_dev_task.v1 envelope
  OUT_DIR     (default /out)             -> result.json, steps.log
  CURSOR_API_KEY, GIT_TOKEN              -> env only; never written anywhere
  CURSOR_AGENT_BIN (optional)            -> defaults to cursor-agent on PATH

Steps (each recorded with exit code and duration):
  clone -> record base_sha -> branch -> cursor -> path guard -> verify ->
  rebase -> commit -> push -> pull request.
Any guard failure ends in status "held" with hold_reason; the branch is not pushed.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BRANCH_RE = re.compile(r"^agent/(roadrunner|reviewer)/req_task_[0-9a-f]{8}-[a-z0-9-]{3,60}$")
REPO_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9._-]+$")
SECRET_PATTERNS = (
    re.compile(r"crsr_[A-Za-z0-9]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
)


class Recorder:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.steps: list[dict[str, Any]] = []
        self.log = (out_dir / "steps.log").open("a", encoding="utf-8")
        self.secrets = [s for s in (os.environ.get("CURSOR_API_KEY"), os.environ.get("GIT_TOKEN")) if s]

    def redact(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "[redacted]")
        return text

    def run(self, step: str, argv: list[str], *, cwd: Path, env: dict[str, str] | None = None,
            timeout: int = 600, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        t0 = time.time()
        try:
            proc = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, text=True,
                                  timeout=timeout, check=False, input=input_text)
            code = int(proc.returncode)
            out, err = proc.stdout or "", proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            code = -1
            out = exc.stdout if isinstance(exc.stdout, str) else ""
            err = ((exc.stderr if isinstance(exc.stderr, str) else "") + "\ntimeout").strip()
            proc = subprocess.CompletedProcess(argv, code, out, err)
        dur = round(time.time() - t0, 3)
        shown = [("[redacted]" if any(s in a for s in self.secrets) else a) for a in argv]
        self.steps.append({"step": step, "argv": shown, "exit_code": code, "duration_s": dur})
        self.log.write(f"## {step} exit={code} dur={dur}s\n$ {' '.join(shown)}\n")
        self.log.write(self.redact(out)[-20000:] + "\n" + self.redact(err)[-20000:] + "\n")
        self.log.flush()
        return proc

    def note(self, step: str, **fields: Any) -> None:
        row = {"step": step, **fields}
        self.steps.append(row)
        self.log.write(f"## {step} {json.dumps(fields, default=str)}\n")
        self.log.flush()


def path_guard(changed: list[str], allow: list[str], deny: list[str]) -> list[str]:
    """Return offending paths (outside allow or inside deny)."""
    bad: list[str] = []
    for path in changed:
        if any(fnmatch.fnmatch(path, pat) for pat in deny):
            bad.append(path)
            continue
        if allow and not any(fnmatch.fnmatch(path, pat) or pat == "**" for pat in allow):
            bad.append(path)
    return bad


def secret_scan(repo: Path, changed: list[str]) -> list[str]:
    hits: list[str] = []
    for rel in changed:
        p = repo / rel
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(pat.search(text) for pat in SECRET_PATTERNS):
            hits.append(rel)
    return hits


def github_json(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "forge-agentic-dev")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return int(exc.code), json.loads(raw)
        except json.JSONDecodeError:
            return int(exc.code), {"message": raw[:500]}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"message": type(exc).__name__}


def finish(out_dir: Path, rec: Recorder, result: dict[str, Any]) -> int:
    result["steps"] = rec.steps
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    rec.log.close()
    return 0 if result.get("status") == "pushed" else 2


def main() -> int:
    task_file = Path(os.environ.get("TASK_FILE") or "/task/task.json")
    out_dir = Path(os.environ.get("OUT_DIR") or "/out")
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = Recorder(out_dir)
    task = json.loads(task_file.read_text(encoding="utf-8"))
    if str(task.get("schema") or "") == "forge.code_review_task.v1":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from run_review import review_main

        review = review_main(task, out_dir, rec)
        review["steps"] = rec.steps
        (out_dir / "result.json").write_text(json.dumps(review, indent=2, default=str) + "\n", encoding="utf-8")
        rec.log.close()
        return 0 if review.get("status") in ("pass", "hold") else 2
    result: dict[str, Any] = {
        "task_id": task.get("task_id"), "repo": task.get("repo"), "branch": task.get("branch"),
        "base_ref": task.get("base_ref") or "main", "base_sha": None, "head_sha": None,
        "pr_url": None, "pr_number": None, "verify": [], "status": "failed", "hold_reason": None,
    }
    repo, branch, base_ref = str(task.get("repo") or ""), str(task.get("branch") or ""), result["base_ref"]
    if not REPO_RE.match(repo) or not BRANCH_RE.match(branch):
        result["hold_reason"] = "invalid_envelope"
        result["status"] = "held"
        return finish(out_dir, rec, result)
    token = os.environ.get("GIT_TOKEN") or ""
    cursor_key = os.environ.get("CURSOR_API_KEY") or ""
    if not token or not cursor_key:
        result["hold_reason"] = "credentials_missing"
        result["status"] = "held"
        return finish(out_dir, rec, result)

    work = Path(os.environ.get("WORK_DIR") or (Path.home() / "work"))
    work.mkdir(parents=True, exist_ok=True)
    checkout = work / "repo"
    git_env = dict(os.environ)
    git_env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME") or "forge-roadrunner",
        "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL") or "roadrunner@forgesdlc.com",
        "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME") or "forge-roadrunner",
        "GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL") or "roadrunner@forgesdlc.com",
    })
    # Token goes through a credential helper, never into the remote URL that git stores.
    helper = work / "git-askpass.sh"
    helper.write_text("#!/bin/sh\ncase \"$1\" in *sername*) echo x-access-token;; *) echo \"$GIT_TOKEN\";; esac\n", encoding="utf-8")
    helper.chmod(0o700)
    git_env["GIT_ASKPASS"] = str(helper)
    remote = f"https://github.com/{repo}.git"

    proc = rec.run("clone", ["git", "clone", "--branch", base_ref, "--single-branch", remote, str(checkout)], cwd=work, env=git_env, timeout=600)
    if proc.returncode != 0:
        result["hold_reason"] = "clone_failed"
        return finish(out_dir, rec, result)
    proc = rec.run("base_sha", ["git", "rev-parse", "HEAD"], cwd=checkout, env=git_env)
    result["base_sha"] = proc.stdout.strip() or None
    rec.run("branch", ["git", "switch", "-c", branch], cwd=checkout, env=git_env)

    model = str(task.get("model") or "composer-2.5")
    goal = str(task.get("goal") or "")
    cursor_bin = os.environ.get("CURSOR_AGENT_BIN") or "cursor-agent"
    cursor_args = [cursor_bin, "--print", "--force", "--trust", "--workspace", str(checkout),
                   "--model", model, "--output-format", "text", goal]
    cursor_env = dict(git_env)
    cursor_env["CURSOR_API_KEY"] = cursor_key
    cursor_timeout = int(task.get("cursor_timeout_s") or 1500)
    proc = rec.run("cursor", cursor_args, cwd=checkout, env=cursor_env, timeout=cursor_timeout)
    (out_dir / "cursor-output.txt").write_text(rec.redact((proc.stdout or "")[-200000:]), encoding="utf-8")
    if proc.returncode != 0:
        result["hold_reason"] = "cursor_failed"
        return finish(out_dir, rec, result)

    rec.run("stage", ["git", "add", "-A"], cwd=checkout, env=git_env)
    proc = rec.run("changed", ["git", "diff", "--cached", "--name-only"], cwd=checkout, env=git_env)
    changed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    result["changed_files"] = changed
    if not changed:
        result["hold_reason"] = "no_changes"
        result["status"] = "held"
        return finish(out_dir, rec, result)
    bad = path_guard(changed, list(task.get("allow_paths") or ["**"]), list(task.get("deny_paths") or []))
    if bad:
        rec.note("path_guard", offending=bad)
        result["hold_reason"] = "path_violation"
        result["offending_paths"] = bad
        result["status"] = "held"
        return finish(out_dir, rec, result)
    hits = secret_scan(checkout, changed)
    if hits:
        rec.note("secret_scan", hits=hits)
        result["hold_reason"] = "secret_pattern"
        result["offending_paths"] = hits
        result["status"] = "held"
        return finish(out_dir, rec, result)

    verify_cmds = [str(c) for c in (task.get("verify") or [])][:8]
    verify_ok = True
    for cmd in verify_cmds:
        proc = rec.run("verify", ["bash", "-lc", cmd], cwd=checkout, env=git_env, timeout=int(task.get("verify_timeout_s") or 900))
        result["verify"].append({"cmd": cmd, "exit_code": proc.returncode})
        verify_ok = verify_ok and proc.returncode == 0
    if not verify_ok:
        result["hold_reason"] = "verify_failed"
        result["status"] = "held"
        return finish(out_dir, rec, result)

    summary = str(task.get("commit_subject") or f"agent({task.get('scope') or 'task'}): {goal[:60].strip()}")
    trailers = f"\n\nForge-Task: {task.get('task_id')}\nForge-Approval: {(task.get('approval') or {}).get('event_id') or ''}\n"
    proc = rec.run("commit", ["git", "commit", "-q", "-m", summary + trailers], cwd=checkout, env=git_env)
    if proc.returncode != 0:
        result["hold_reason"] = "commit_failed"
        return finish(out_dir, rec, result)

    rec.run("fetch", ["git", "fetch", "-q", "origin", base_ref], cwd=checkout, env=git_env, timeout=300)
    proc = rec.run("rebase", ["git", "rebase", f"origin/{base_ref}"], cwd=checkout, env=git_env, timeout=300)
    if proc.returncode != 0:
        proc2 = rec.run("conflicts", ["git", "diff", "--name-only", "--diff-filter=U"], cwd=checkout, env=git_env)
        rec.run("rebase_abort", ["git", "rebase", "--abort"], cwd=checkout, env=git_env)
        result["hold_reason"] = "stale_conflict"
        result["conflicts"] = [l.strip() for l in proc2.stdout.splitlines() if l.strip()]
        result["status"] = "held"
        return finish(out_dir, rec, result)

    proc = rec.run("push", ["git", "push", "-q", "origin", f"{branch}:{branch}"], cwd=checkout, env=git_env, timeout=300)
    if proc.returncode != 0:
        result["hold_reason"] = "push_failed"
        return finish(out_dir, rec, result)
    proc = rec.run("head_sha", ["git", "rev-parse", "HEAD"], cwd=checkout, env=git_env)
    result["head_sha"] = proc.stdout.strip() or None

    test_lines = [f"git fetch origin {branch} && git checkout {branch}   # head {str(result['head_sha'])[:12]}"]
    test_lines += [f"{c}   # expected: exit 0" for c in verify_cmds]
    body = (
        f"Forge task `{task.get('task_id')}` on `{repo}` (agent lane).\n\n"
        f"**Goal:** {goal}\n\n**Base:** `{base_ref}` @ `{result['base_sha']}`\n\n"
        f"**Verify:** " + ", ".join(f"`{v['cmd']}` → {v['exit_code']}" for v in result["verify"]) + "\n\n"
        "**Test it locally**\n```\n" + "\n".join(test_lines) + "\n```\n\n"
        f"Approval: `{(task.get('approval') or {}).get('event_id') or ''}`. "
        "Merge is performed by the review worker after operator `confirm`."
    )
    status, resp = github_json("POST", f"https://api.github.com/repos/{repo}/pulls", token,
                               {"title": summary[:200], "head": branch, "base": base_ref, "body": body, "draft": False})
    rec.note("pull_request", http=status, number=resp.get("number"))
    if status in (200, 201):
        result["pr_url"] = resp.get("html_url")
        result["pr_number"] = resp.get("number")
    else:
        result["pr_error"] = str(resp.get("message") or status)[:300]
    result["test_instructions"] = test_lines
    result["status"] = "pushed"
    return finish(out_dir, rec, result)


if __name__ == "__main__":
    sys.exit(main())
