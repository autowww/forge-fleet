"""Roadrunner rollout: git sync of autowww/forge-agents on this host, compose build, managed-service up.

Git is the only code carrier (no bundles, no SSH). Secrets stay in the operator-owned
``<root>/.env.roadrunner`` on the host; this module never writes or logs them.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import container_layout

SERVICE_ID = "forge-agents-roadrunner"
TYPE_ID = "forge_agents_roadrunner"
REPO_URL = "https://github.com/autowww/forge-agents.git"
COMPOSE_REL = Path("deploy") / "roadrunner"
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"running": False, "last": None}


def repo_root() -> Path:
    raw = os.environ.get("FLEET_FORGE_AGENTS_ROOT") or "~/forge-agents"
    return Path(raw).expanduser()


def log_path(data_dir: Path) -> Path:
    return data_dir / "forge-agents-rollout.log"


def git_sync_argv(root: Path, ref: str) -> list[list[str]]:
    """Commands to bring ``root`` to ``origin/<ref>`` (clone when missing). Never force-pushes anything."""
    if (root / ".git").is_dir():
        return [
            ["git", "-C", str(root), "fetch", "--prune", "origin"],
            ["git", "-C", str(root), "checkout", "-q", ref],
            ["git", "-C", str(root), "reset", "-q", "--hard", f"origin/{ref}"],
        ]
    return [["git", "clone", "--branch", ref, REPO_URL, str(root)]]


def _run(cmd: list[str], log, *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: int = 900) -> int:
    log.write(f"$ {' '.join(cmd)}\n")
    log.flush()
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as ex:
        log.write(f"! {type(ex).__name__}: {str(ex)[:300]}\n")
        return 127
    if r.stdout:
        log.write(r.stdout[-4000:] + "\n")
    if r.stderr:
        log.write(r.stderr[-4000:] + "\n")
    log.flush()
    return int(r.returncode)


def _head_sha(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _rollout(data_dir: Path, *, ref: str, docker_bin: str) -> dict[str, Any]:
    root = repo_root()
    started = time.time()
    result: dict[str, Any] = {"ok": False, "service_id": SERVICE_ID, "ref": ref, "root": str(root), "steps": []}
    data_dir.mkdir(parents=True, exist_ok=True)
    with log_path(data_dir).open("a", encoding="utf-8") as log:
        log.write(f"\n=== rollout {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} ref={ref} root={root}\n")
        for cmd in git_sync_argv(root, ref):
            if _run(cmd, log, timeout=300) != 0:
                result["error"] = "git_sync_failed"
                result["steps"].append({"step": "git", "ok": False})
                return result
        result["steps"].append({"step": "git", "ok": True})
        sha = _head_sha(root)
        result["git_sha"] = sha
        if not (root / ".env.roadrunner").is_file():
            result["error"] = "env_roadrunner_missing"
            result["detail"] = f"create {root}/.env.roadrunner on the host (MATRIX_*, FORGE_FLEET_BEARER_TOKEN); operator step"
            return result
        compose_dir = root / COMPOSE_REL
        if not (compose_dir / "compose.yaml").is_file():
            result["error"] = "compose_missing"
            return result
        env = os.environ.copy()
        env["ROADRUNNER_GIT_SHA"] = sha or "dev"
        (compose_dir / ".env").write_text(f"ROADRUNNER_GIT_SHA={sha or 'dev'}\n", encoding="utf-8")
        if _run([docker_bin, "compose", "-f", "compose.yaml", "build", "--pull"], log, cwd=compose_dir, env=env, timeout=1200) != 0:
            result["error"] = "compose_build_failed"
            result["steps"].append({"step": "build", "ok": False})
            return result
        result["steps"].append({"step": "build", "ok": True})
        try:
            container_layout.ensure_layout(data_dir)
            container_layout.upsert_service(
                data_dir, service_id=SERVICE_ID, type_id=TYPE_ID, compose_root=str(compose_dir), compose_files=[],
                label="Roadrunner (Matrix -> agentic dev rail)", allow_replace=True,
            )
            result["steps"].append({"step": "register", "ok": True})
        except (ValueError, FileNotFoundError) as ex:
            result["error"] = f"register_failed:{str(ex)[:200]}"
            return result
        if _run([docker_bin, "compose", "-f", "compose.yaml", "up", "-d", "--remove-orphans"], log, cwd=compose_dir, env=env, timeout=600) != 0:
            result["error"] = "compose_up_failed"
            result["steps"].append({"step": "up", "ok": False})
            return result
        result["steps"].append({"step": "up", "ok": True})
        health = ""
        for _ in range(20):
            time.sleep(3)
            try:
                import urllib.request

                with urllib.request.urlopen("http://127.0.0.1:9788/health", timeout=5) as resp:
                    health = resp.read().decode("utf-8", errors="replace")[:400]
                    break
            except OSError:
                continue
        result["health"] = health or None
        result["ok"] = bool(health)
        if not health:
            result["error"] = "health_timeout"
        result["elapsed_s"] = round(time.time() - started, 1)
        log.write(json.dumps({k: v for k, v in result.items() if k != "steps"}) + "\n")
    return result


def schedule(data_dir: Path, body: dict[str, Any], *, sync: bool = False) -> dict[str, Any]:
    ref = str(body.get("ref") or "main").strip()
    if not ref or any(c in ref for c in " ;&|$`\\") or ref.startswith("-"):
        return {"http": 400, "ok": False, "error": "invalid_ref"}
    docker_bin = os.environ.get("FLEET_DOCKER_BIN") or "docker"
    with _LOCK:
        if _STATE["running"]:
            return {"http": 409, "ok": False, "error": "rollout_in_progress"}
        _STATE["running"] = True

    def _go() -> dict[str, Any]:
        try:
            out = _rollout(data_dir, ref=ref, docker_bin=docker_bin)
        except Exception as ex:  # noqa: BLE001
            out = {"ok": False, "error": f"rollout_crashed:{type(ex).__name__}"}
        finally:
            with _LOCK:
                _STATE["running"] = False
        _STATE["last"] = out
        return out

    if sync:
        out = _go()
        return {"http": 200 if out.get("ok") else 502, **out}
    threading.Thread(target=_go, name="forge-agents-rollout", daemon=True).start()
    return {"http": 202, "ok": True, "status": "scheduled", "ref": ref, "log": str(log_path(data_dir))}


def status(data_dir: Path, *, max_bytes: int = 12000) -> dict[str, Any]:
    p = log_path(data_dir)
    tail = ""
    if p.is_file():
        data = p.read_bytes()
        tail = data[-max_bytes:].decode("utf-8", errors="replace")
    return {"ok": True, "running": bool(_STATE["running"]), "last": _STATE["last"], "log_tail": tail}
