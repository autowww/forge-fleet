"""Agentic dev rail: one approved repo task in an ephemeral container.

``POST /v1/admin/agentic-dev-task`` accepts a ``forge.agentic_dev_task.v1``
envelope. The container (``deploy/agentic-dev``) clones ``origin/<base_ref>``
from GitHub, records ``base_sha``, works on an ``agent/*`` branch, verifies,
rebases, pushes the branch, and opens a pull request. Git is the only code
carrier; no host path is mounted into the container.

Credentials: the git token is read from the Fleet host environment
(``FLEET_AGENTIC_GIT_TOKEN``). The Cursor key arrives from localhost either in
the submit body or later through ``POST .../<id>/credential`` (courier). Neither
is stored in a job row; output is redacted.

Peer spread (R10): ``node`` may be ``local`` (default), ``auto``, or a
registered remote peer id. Non-local work is forwarded through the remote
peer proxy with the credential attached on the forwarding hop only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from fleet_server import cursor_cli_job, remote_peers, store

JOB_KIND = "agentic_dev_task"
REVIEW_KIND = "code_review_task"
CONTAINER_CLASS = "agentic_dev"
STATUS_WAITING = "queued_waiting_credential"

_REPO_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9._-]+$")
_BRANCH_RE = re.compile(r"^agent/(roadrunner|reviewer)/req_task_[0-9a-f]{8}-[a-z0-9-]{3,60}$")
_TASK_ID_RE = re.compile(r"^req_task_[0-9a-f]{8}$")
_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_GOAL = 8000
_MAX_VERIFY = 8
_MAX_PATHS = 32
_MIN_TIMEOUT = 60
_MAX_TIMEOUT = 3600
_DEFAULT_TIMEOUT = 1800
_IMAGE_LOCK = threading.Lock()
_DEFAULT_DENY = [".github/**", "**/*.env", "**/secrets*", "**/*.pem", "**/*.key"]


def _truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def repo_allowlist() -> list[str]:
    raw = str(os.environ.get("FLEET_AGENTIC_REPO_ALLOWLIST") or "autowww/*")
    return [p.strip() for p in raw.split(",") if p.strip()]


def repo_allowed(repo: str) -> bool:
    return any(fnmatch(repo, pat) for pat in repo_allowlist())


def git_token() -> str:
    return str(os.environ.get("FLEET_AGENTIC_GIT_TOKEN") or "").strip()


def deploy_dir() -> Path:
    override = str(os.environ.get("FLEET_AGENTIC_DEV_DEPLOY_DIR") or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "deploy" / "agentic-dev"


def runner_mode() -> str:
    mode = str(os.environ.get("FLEET_AGENTIC_DEV_RUNNER") or "docker").strip().lower()
    return mode if mode in ("docker", "host") else "docker"


def _reject(http: int, error: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"http": http, "ok": False, "error": error}
    out.update(extra)
    return out


def redact(text: str, *secrets: str) -> str:
    cleaned = text or ""
    for s in secrets:
        if s:
            cleaned = cleaned.replace(s, "[redacted]")
    return cursor_cli_job.redact(cleaned, "")


_SECRET_TOKEN_RE = re.compile(r"(crsr_[A-Za-z0-9]+|ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)")


def redact_obj(value: Any, *secrets: str) -> Any:
    """Structural redaction for JSON results (no truncation, no whitespace rewrite)."""
    if isinstance(value, str):
        out = value
        for s in secrets:
            if s:
                out = out.replace(s, "[redacted]")
        return _SECRET_TOKEN_RE.sub("[redacted]", out)
    if isinstance(value, list):
        return [redact_obj(v, *secrets) for v in value]
    if isinstance(value, dict):
        return {str(k): redact_obj(v, *secrets) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------- status endpoints


def cursor_cli_status() -> dict[str, Any]:
    """Binary path and version of the host Cursor CLI, and whether the container rail is ready."""
    binary = cursor_cli_job.configured_binary()
    version = ""
    if binary:
        try:
            proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=15, check=False)
            version = (proc.stdout or proc.stderr or "").strip().splitlines()[0][:120] if (proc.stdout or proc.stderr) else ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            version = f"error:{type(exc).__name__}"
    docker = shutil.which("docker") or shutil.which("podman")
    deploy = deploy_dir()
    return {
        "ok": bool(binary) or (runner_mode() == "docker" and bool(docker) and (deploy / "Dockerfile").is_file()),
        "host_binary": binary,
        "host_version": version,
        "runner": runner_mode(),
        "docker": bool(docker),
        "image": image_tag(),
        "deploy_dir_present": (deploy / "Dockerfile").is_file() and (deploy / "run_task.py").is_file(),
        "git_token_configured": bool(git_token()),
        "repo_allowlist": repo_allowlist(),
    }


def git_identity() -> dict[str, Any]:
    """Login and token kind for the Granite-held git identity. Never echoes the token."""
    token = git_token()
    if not token:
        return {"ok": False, "error": "git_token_not_configured"}
    req = urllib.request.Request("https://api.github.com/user", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "forge-fleet-agentic-dev")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            doc = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
            scopes = resp.headers.get("X-OAuth-Scopes") or ""
            expiry = resp.headers.get("GitHub-Authentication-Token-Expiration") or ""
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"github_http_{exc.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": f"github_unreachable:{type(exc).__name__}"}
    kind = "fine_grained_pat" if token.startswith("github_pat_") else ("classic_pat" if token.startswith("ghp_") else "token")
    return {
        "ok": True,
        "login": str(doc.get("login") or ""),
        "token_kind": kind,
        "classic_scopes": scopes,
        "expires_hint": expiry,
        "repo_allowlist": repo_allowlist(),
    }


# --------------------------------------------------------------------------- envelope


def _str_list(value: object, *, max_items: int, max_len: int) -> list[str] | None:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > max_items:
        return None
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > max_len or "\x00" in item:
            return None
        out.append(item.strip())
    return out


def validate_envelope(body: dict[str, Any], *, kind: str = JOB_KIND) -> tuple[dict[str, Any] | None, str | None]:
    """Return (envelope, None) or (None, error)."""
    task_id = str(body.get("task_id") or "").strip()
    if not _TASK_ID_RE.match(task_id):
        return None, "invalid_task_id"
    repo = str(body.get("repo") or "").strip()
    if not _REPO_RE.match(repo):
        return None, "invalid_repo"
    if not repo_allowed(repo):
        return None, "repo_not_allowed"
    base_ref = str(body.get("base_ref") or "main").strip()
    if not _REF_RE.match(base_ref) or ".." in base_ref:
        return None, "invalid_base_ref"
    branch = str(body.get("branch") or "").strip()
    if not _BRANCH_RE.match(branch):
        return None, "invalid_branch"
    if not branch.startswith("agent/") or task_id not in branch:
        return None, "branch_task_mismatch"
    goal = str(body.get("goal") or "")
    if kind == JOB_KIND and (not goal.strip() or len(goal) > _MAX_GOAL):
        return None, "invalid_goal"
    verify = _str_list(body.get("verify"), max_items=_MAX_VERIFY, max_len=500)
    allow = _str_list(body.get("allow_paths"), max_items=_MAX_PATHS, max_len=200)
    deny = _str_list(body.get("deny_paths"), max_items=_MAX_PATHS, max_len=200)
    if verify is None or allow is None or deny is None:
        return None, "invalid_lists"
    model = str(body.get("model") or "composer-2.5").strip()
    if not _MODEL_RE.match(model):
        return None, "invalid_model"
    timeout = body.get("timeout_s", _DEFAULT_TIMEOUT)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < _MIN_TIMEOUT or timeout > _MAX_TIMEOUT:
        return None, "invalid_timeout"
    approval = body.get("approval") if isinstance(body.get("approval"), dict) else {}
    digest = str(approval.get("digest") or "")
    if digest and not _DIGEST_RE.match(digest):
        return None, "invalid_approval_digest"
    report = body.get("report") if isinstance(body.get("report"), dict) else {}
    node = str(body.get("node") or "local").strip().lower()
    if not re.match(r"^[a-z][a-z0-9_-]{0,63}$", node):
        return None, "invalid_node"
    envelope: dict[str, Any] = {
        "schema": "forge.agentic_dev_task.v1" if kind == JOB_KIND else "forge.code_review_task.v1",
        "task_id": task_id,
        "repo": repo,
        "base_ref": base_ref,
        "branch": branch,
        "goal": goal,
        "verify": verify,
        "allow_paths": allow or ["**"],
        "deny_paths": deny or list(_DEFAULT_DENY),
        "model": model,
        "timeout_s": timeout,
        "approval": {
            "request_id": str(approval.get("request_id") or task_id),
            "digest": digest,
            "event_id": str(approval.get("event_id") or ""),
        },
        "report": {"room_id": str(report.get("room_id") or ""), "thread_root": str(report.get("thread_root") or "")},
        "node": node,
    }
    if kind == REVIEW_KIND:
        pr = body.get("pr_number")
        head = str(body.get("head_sha") or "")
        if not isinstance(pr, int) or isinstance(pr, bool) or pr <= 0 or not re.match(r"^[0-9a-f]{40}$", head):
            return None, "invalid_review_target"
        envelope["pr_number"] = pr
        envelope["head_sha"] = head
    return envelope, None


def canonical_digest(envelope: dict[str, Any]) -> str:
    """Digest over the fields the ``!approve`` receipt binds (not ``base_sha``, not ``node``)."""
    bound = {k: envelope[k] for k in ("repo", "base_ref", "branch", "goal", "verify", "allow_paths", "deny_paths", "model", "timeout_s")}
    raw = json.dumps(bound, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- submit / attach / get


def _credential_from(body: dict[str, Any]) -> tuple[str | None, str | None]:
    secret = body.get("credential")
    ref = str(body.get("credential_ref") or "").strip().lower()
    if isinstance(secret, str) and secret.strip():
        if secret != secret.strip():
            return None, "credential_required"
        return secret, None
    if ref == "courier":
        return "", None
    return None, "credential_required"


def _secret_leaks(secret: str, body: dict[str, Any]) -> bool:
    if not secret:
        return False
    public = {k: v for k, v in body.items() if k != "credential"}
    return secret in json.dumps(public, default=str)


def submit(db_path: Path, data_dir: Path, body: object, *, inline: bool = False, kind: str = JOB_KIND) -> dict[str, Any]:
    if not isinstance(body, dict):
        return _reject(400, "invalid_body")
    envelope, err = validate_envelope(body, kind=kind)
    if err or envelope is None:
        return _reject(400, err or "invalid_envelope")
    secret, cerr = _credential_from(body)
    if cerr or secret is None:
        return _reject(400, cerr or "credential_required")
    if _secret_leaks(secret, body):
        return _reject(400, "credential_in_request")
    if json.dumps(envelope).find("crsr_") >= 0:
        return _reject(400, "credential_in_request")
    if not git_token():
        return _reject(400, "git_token_not_configured")
    if envelope["node"] not in ("local", "auto"):
        return _forward(data_dir, envelope, secret, kind=kind)
    if envelope["node"] == "auto":
        chosen = choose_node(db_path, data_dir)
        if chosen != "local":
            envelope["node"] = chosen
            return _forward(data_dir, envelope, secret, kind=kind)
        envelope["node"] = "local"
    status_ready = cursor_cli_status()
    if not status_ready.get("ok"):
        return _reject(400, "agentic_dev_not_configured", status=status_ready)
    digest = canonical_digest(envelope)
    bound = envelope["approval"].get("digest")
    if bound and bound != digest:
        return _reject(409, "approval_digest_mismatch", expected=digest)
    conn = store.connect(db_path)
    try:
        job_id = store.insert_job(
            conn,
            kind=kind,
            argv=[],
            session_id="",
            meta={
                "container_class": CONTAINER_CLASS,
                "envelope": envelope,
                "digest": digest,
                "credential_attached": bool(secret),
                "timeout_s": envelope["timeout_s"],
                "node": envelope["node"],
            },
        )
        if not secret:
            store.update_job(conn, job_id, status=STATUS_WAITING)
    finally:
        conn.close()
    if secret:
        _start(db_path, data_dir, job_id, envelope, secret, inline=inline)
        return {"http": 202, "ok": True, "id": job_id, "status": "queued", "digest": digest, "node": envelope["node"]}
    return {"http": 202, "ok": True, "id": job_id, "status": STATUS_WAITING, "digest": digest, "node": envelope["node"]}


def attach_credential(db_path: Path, data_dir: Path, job_id: str, body: object, *, inline: bool = False) -> dict[str, Any]:
    if not isinstance(body, dict):
        return _reject(400, "invalid_body")
    secret = body.get("credential")
    if not isinstance(secret, str) or not secret.strip() or secret != secret.strip():
        return _reject(400, "credential_required")
    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
        if row is None or row.get("kind") not in (JOB_KIND, REVIEW_KIND):
            return _reject(404, "not_found")
        if row.get("status") != STATUS_WAITING:
            return _reject(409, "credential_already_attached_or_started", status=row.get("status"))
        meta = dict(row.get("meta") or {})
        envelope = meta.get("envelope") if isinstance(meta.get("envelope"), dict) else None
        if envelope is None:
            return _reject(409, "envelope_missing")
        store.merge_job_meta(conn, job_id, {"credential_attached": True})
        store.update_job(conn, job_id, status="queued")
    finally:
        conn.close()
    _start(db_path, data_dir, job_id, envelope, secret, inline=inline)
    return {"http": 202, "ok": True, "id": job_id, "status": "queued"}


def get(db_path: Path, job_id: str) -> dict[str, Any]:
    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
    finally:
        conn.close()
    if row is None or row.get("kind") not in (JOB_KIND, REVIEW_KIND):
        return _reject(404, "not_found")
    meta = row.get("meta") or {}
    return {
        "http": 200,
        "ok": True,
        "id": job_id,
        "kind": row.get("kind"),
        "status": row.get("status"),
        "exit_code": row.get("exit_code"),
        "node": meta.get("node"),
        "digest": meta.get("digest"),
        "envelope": meta.get("envelope"),
        "result": row.get("worker_result"),
        "stderr_tail": str(row.get("stderr") or "")[-2000:],
        "created": row.get("created"),
        "updated": row.get("updated"),
    }


# --------------------------------------------------------------------------- peers (R10)


def list_pending_credentials(db_path: Path, *, max_age_s: int = 3600) -> dict[str, Any]:
    """Jobs waiting for the localhost courier: id, task_id, repo, digest, age. No secrets, no goal text."""
    conn = store.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT id, kind, meta_json, created FROM jobs WHERE status = ? AND kind IN (?, ?) ORDER BY created ASC LIMIT 50",
            (STATUS_WAITING, JOB_KIND, REVIEW_KIND),
        )
        now = time.time()
        rows: list[dict[str, Any]] = []
        for r in cur.fetchall():
            try:
                meta = json.loads(r["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            env = meta.get("envelope") if isinstance(meta, dict) and isinstance(meta.get("envelope"), dict) else {}
            age = max(0, int(now - float(r["created"] or now)))
            rows.append(
                {
                    "id": str(r["id"]),
                    "kind": str(r["kind"]),
                    "task_id": env.get("task_id"),
                    "repo": env.get("repo"),
                    "branch": env.get("branch"),
                    "digest": meta.get("digest") if isinstance(meta, dict) else None,
                    "approval": env.get("approval"),
                    "age_s": age,
                    "expired": age > max_age_s,
                }
            )
    finally:
        conn.close()
    return {"ok": True, "pending": rows}


def peer_capacity(data_dir: Path, peer_id: str) -> dict[str, Any]:
    code, raw, _ = remote_peers.proxy_get(data_dir, peer_id, "/v1/admin/agentic-dev/capacity")
    try:
        doc = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        doc = {}
    return {"http": code, **(doc if isinstance(doc, dict) else {})}


def local_capacity(db_path: Path) -> dict[str, Any]:
    try:
        limit = int(os.environ.get("FLEET_AGENTIC_DEV_MAX_RUNNING") or 2)
    except ValueError:
        limit = 2
    conn = store.connect(db_path)
    try:
        running = store.count_running_jobs_by_container_class(conn).get(CONTAINER_CLASS, 0)
    finally:
        conn.close()
    return {"ok": True, "node": "local", "agentic_dev": _truthy("FLEET_AGENTIC_DEV_NODE") or runner_mode() == "host" or bool(git_token()),
            "max_running": limit, "running": running, "free": max(0, limit - running)}


def choose_node(db_path: Path, data_dir: Path) -> str:
    """Local when it has a free slot; else the first labelled peer with free capacity."""
    local = local_capacity(db_path)
    if local.get("free", 0) > 0:
        return "local"
    peers = remote_peers.list_peers(data_dir).get("peers") or []
    for peer in peers:
        pid = str(peer.get("id") or "")
        if not pid:
            continue
        cap = peer_capacity(data_dir, pid)
        if cap.get("http") == 200 and cap.get("agentic_dev") and int(cap.get("free") or 0) > 0:
            return pid
    return "local"


def _forward(data_dir: Path, envelope: dict[str, Any], secret: str, *, kind: str) -> dict[str, Any]:
    peer_id = envelope["node"]
    if remote_peers.get_peer(data_dir, peer_id) is None:
        return _reject(409, "peer_unavailable", node=peer_id)
    body = dict(envelope)
    body["node"] = "local"
    if secret:
        body["credential"] = secret
    else:
        body["credential_ref"] = "courier"
    path = "/v1/admin/agentic-dev-task" if kind == JOB_KIND else "/v1/admin/code-review-task"
    code, raw, _ = remote_peers.proxy_json(data_dir, peer_id, path, method="POST",
                                           body=json.dumps(body).encode("utf-8"), timeout_s=60.0)
    body["credential"] = ""
    try:
        doc = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        doc = {"error": "peer_invalid_response"}
    out = {"http": code if code else 502, **(doc if isinstance(doc, dict) else {})}
    out["node"] = peer_id
    out["forwarded"] = True
    return out


# --------------------------------------------------------------------------- execution


def image_tag() -> str:
    override = str(os.environ.get("FLEET_AGENTIC_DEV_IMAGE") or "").strip()
    if override:
        return override
    deploy = deploy_dir()
    h = hashlib.sha256()
    for name in ("Dockerfile", "run_task.py"):
        p = deploy / name
        if p.is_file():
            h.update(p.read_bytes())
    return f"forge-agentic-dev:{h.hexdigest()[:12]}"


def ensure_image(log: list[str]) -> str | None:
    """Build the container image from ``deploy/agentic-dev`` on this host when missing."""
    tag = image_tag()
    docker = shutil.which("docker") or shutil.which("podman")
    if not docker:
        log.append("docker_missing")
        return None
    with _IMAGE_LOCK:
        probe = subprocess.run([docker, "image", "inspect", tag], capture_output=True, text=True, check=False)
        if probe.returncode == 0:
            return tag
        if str(os.environ.get("FLEET_AGENTIC_DEV_IMAGE") or "").strip():
            log.append("image_missing")
            return None
        build = subprocess.run([docker, "build", "-t", tag, str(deploy_dir())], capture_output=True, text=True,
                               timeout=1800, check=False)
        if build.returncode != 0:
            log.append("image_build_failed: " + (build.stderr or build.stdout or "")[-2000:])
            return None
    return tag


def _start(db_path: Path, data_dir: Path, job_id: str, envelope: dict[str, Any], secret: str, *, inline: bool) -> None:
    if inline:
        _execute(db_path, data_dir, job_id, envelope, secret)
        return
    threading.Thread(target=_execute, args=(db_path, data_dir, job_id, envelope, secret), daemon=True).start()


def _job_dir(data_dir: Path, job_id: str) -> Path:
    return (data_dir / "agentic-dev" / job_id).resolve()


def _execute(db_path: Path, data_dir: Path, job_id: str, envelope: dict[str, Any], secret: str) -> None:
    conn = store.connect(db_path)
    try:
        store.update_job(conn, job_id, status="running", running_started=time.time())
    finally:
        conn.close()
    jdir = _job_dir(data_dir, job_id)
    task_dir, out_dir = jdir / "task", jdir / "out"
    task_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    public_task = dict(envelope)
    (task_dir / "task.json").write_text(json.dumps(public_task, indent=2) + "\n", encoding="utf-8")
    token = git_token()
    log: list[str] = []
    code = 1
    stderr = ""
    try:
        if runner_mode() == "host":
            code, stderr = _run_host(task_dir, out_dir, envelope, secret, token)
        else:
            code, stderr = _run_docker(job_id, task_dir, out_dir, envelope, secret, token, log)
    except Exception as exc:  # noqa: BLE001 — recorded, never raised into the server thread
        stderr = f"{type(exc).__name__}: {exc}"
    result: dict[str, Any] | None = None
    rp = out_dir / "result.json"
    if rp.is_file():
        try:
            result = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = None
    status = "failed"
    if isinstance(result, dict):
        status = {"pushed": "completed", "held": "held", "failed": "failed", "pass": "completed", "hold": "held"}.get(str(result.get("status")), "failed")
    stored_err = redact("\n".join(log + [stderr]), secret, token)
    secret_copy = secret
    secret = ""
    conn = store.connect(db_path)
    try:
        if isinstance(result, dict):
            store.set_worker_result(conn, job_id, redact_obj(result, secret_copy, token))
        store.update_job(conn, job_id, status=status, stderr=stored_err, exit_code=code)
    finally:
        conn.close()
        secret_copy = ""


def _run_host(task_dir: Path, out_dir: Path, envelope: dict[str, Any], secret: str, token: str) -> tuple[int, str]:
    script = deploy_dir() / "run_task.py"
    work = Path(tempfile.mkdtemp(prefix="fleet-agentic-"))
    env = {
        "PATH": os.environ.get("PATH") or "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(work),
        "LANG": "C.UTF-8",
        "TASK_FILE": str(task_dir / "task.json"),
        "OUT_DIR": str(out_dir),
        "WORK_DIR": str(work / "work"),
        "CURSOR_API_KEY": secret,
        "GIT_TOKEN": token,
    }
    binary = cursor_cli_job.configured_binary()
    if binary:
        env["CURSOR_AGENT_BIN"] = binary
    try:
        proc = subprocess.run(["python3", str(script)], env=env, capture_output=True, text=True,
                              timeout=int(envelope["timeout_s"]) + 60, check=False)
        return int(proc.returncode), (proc.stderr or "")[-4000:]
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run_docker(job_id: str, task_dir: Path, out_dir: Path, envelope: dict[str, Any], secret: str, token: str,
                log: list[str]) -> tuple[int, str]:
    tag = ensure_image(log)
    if not tag:
        return 1, "image_unavailable"
    docker = shutil.which("docker") or shutil.which("podman") or "docker"
    name = f"fleet-agentic-{job_id[:12]}"
    env_file = task_dir / ".env.runtime"
    env_file.write_text(f"CURSOR_API_KEY={secret}\nGIT_TOKEN={token}\n", encoding="utf-8")
    os.chmod(env_file, 0o600)
    argv = [
        docker, "run", "--rm", "--name", name,
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--pids-limit", "1024", "--memory", os.environ.get("FLEET_AGENTIC_DEV_MEMORY") or "4g",
        "--cpus", os.environ.get("FLEET_AGENTIC_DEV_CPUS") or "2",
        "--env-file", str(env_file),
        "-e", "TASK_FILE=/task/task.json", "-e", "OUT_DIR=/out",
        "-v", f"{task_dir}:/task:ro", "-v", f"{out_dir}:/out",
        tag,
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=int(envelope["timeout_s"]) + 120, check=False)
        return int(proc.returncode), (proc.stderr or "")[-4000:]
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "kill", name], capture_output=True, check=False)
        return -1, "timeout"
    finally:
        try:
            env_file.unlink()
        except OSError:
            pass
