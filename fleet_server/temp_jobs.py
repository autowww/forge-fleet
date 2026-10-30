"""Host temp jobs. Results are JSON summaries. Filing bytes are not returned."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from fleet_server import store

KIND = "temp_job"
_MAX_RESULT = 512_000
_DEFAULT_TIMEOUT = 60
_MAX_TIMEOUT = 900
_MODULE_PREFIXES = ("forge_market.analysis.sec_fic.financial_facts",)
_SOURCE_MARKERS = ("<ix:nonfraction", "<html", "original.html")
_MARKET_CONTAINERS = ("forge-market-app", "forge-market-app-dev")


def _reject(http: int, error: str) -> dict[str, Any]:
    return {"http": http, "ok": False, "error": error}


def _module_allowed(module: str) -> bool:
    if not module or ".." in module or module.startswith("."):
        return False
    return any(module == prefix or module.startswith(prefix + ".") for prefix in _MODULE_PREFIXES)


def _accept_result(text: str) -> dict[str, Any] | None:
    if len(text) > _MAX_RESULT:
        return None
    lowered = text.lower()
    if any(marker in lowered for marker in _SOURCE_MARKERS):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def submit(db_path: Path, body: object, *, inline: bool = False) -> dict[str, Any]:
    if not isinstance(body, dict):
        return _reject(400, "invalid_body")
    recipe = str(body.get("recipe") or "").strip()
    if recipe not in {"probe", "python_module"}:
        return _reject(400, "unknown_recipe")
    timeout = body.get("timeout_s", _DEFAULT_TIMEOUT)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > _MAX_TIMEOUT:
        return _reject(400, "invalid_timeout")
    module = str(body.get("module") or "").strip()
    if recipe == "python_module" and not _module_allowed(module):
        return _reject(400, "module_not_allowed")
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    if len(json.dumps(args)) > 8000:
        return _reject(400, "args_too_large")
    argv = ["probe"] if recipe == "probe" else [os.environ.get("FLEET_TEMP_JOB_PYTHON") or sys.executable, "-m", module]
    conn = store.connect(db_path)
    try:
        job_id = store.insert_job(
            conn,
            kind=KIND,
            argv=argv,
            session_id="",
            meta={"recipe": recipe, "module": module, "timeout_s": timeout},
        )
    finally:
        conn.close()
    if inline:
        _execute(db_path, job_id, recipe, module, args, timeout)
    else:
        threading.Thread(
            target=_execute,
            args=(db_path, job_id, recipe, module, args, timeout),
            daemon=True,
        ).start()
    return {"http": 202, "ok": True, "id": job_id, "status": "queued", "recipe": recipe}


def _running_market_container() -> str | None:
    for name in _MARKET_CONTAINERS:
        try:
            proc = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode == 0 and proc.stdout.strip() == "true":
            return name
    return None


def module_command(module: str) -> list[str]:
    """Run the allowlisted module on the host, or inside Market Studio when that container is running."""
    override = (os.environ.get("FLEET_TEMP_JOB_PYTHON") or "").strip()
    if override:
        return [override, "-m", module]
    selected = (os.environ.get("FLEET_TEMP_JOB_CONTAINER") or "").strip()
    if selected == "0" or (selected and selected not in _MARKET_CONTAINERS):
        return [sys.executable, "-m", module]
    container = selected or _running_market_container()
    if container:
        return ["docker", "exec", "-i", "-e", "FLEET_TEMP_JOB_ARGS", container, "python", "-m", module]
    return [sys.executable, "-m", module]


def _redact(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in _SOURCE_MARKERS):
        return "redacted"
    return text[-2000:]


def _execute(db_path: Path, job_id: str, recipe: str, module: str, args: dict[str, Any], timeout: int) -> None:
    if recipe == "probe":
        _store(db_path, job_id, 0, json.dumps({"ok": True, "recipe": "probe", "args": args}), "")
        return
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "FLEET_TEMP_JOB_ARGS": json.dumps(args)}
    code = 1
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            module_command(module),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        code = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        stderr = "timeout"
        code = -1
    except OSError as exc:
        stderr = type(exc).__name__
    stderr = _redact(stderr)
    if code != 0 or _accept_result(stdout) is None:
        _store(db_path, job_id, 1 if code == 0 else code, json.dumps({"ok": False, "error": "result_rejected"}), stderr)
        return
    _store(db_path, job_id, 0, stdout, stderr)


def _store(db_path: Path, job_id: str, code: int, stdout: str, stderr: str) -> None:
    status = "completed" if code == 0 and _accept_result(stdout) is not None else "failed"
    conn = store.connect(db_path)
    try:
        store.update_job(conn, job_id, status=status, stdout=stdout[:_MAX_RESULT], stderr=stderr, exit_code=code)
    finally:
        conn.close()


def status(db_path: Path, job_id: str) -> dict[str, Any]:
    row = _row(db_path, job_id)
    if row is None:
        return _reject(404, "not_found")
    return {
        "http": 200,
        "ok": True,
        "id": row["id"],
        "status": row["status"],
        "recipe": (row.get("meta") or {}).get("recipe"),
        "exit_code": row.get("exit_code"),
    }


def result(db_path: Path, job_id: str) -> dict[str, Any]:
    row = _row(db_path, job_id)
    if row is None:
        return _reject(404, "not_found")
    if row["status"] != "completed":
        return {"http": 409, "ok": False, "error": "not_ready", "status": row["status"]}
    parsed = _accept_result(str(row.get("stdout") or ""))
    if parsed is None:
        return _reject(409, "result_rejected")
    return {"http": 200, "ok": True, "id": job_id, "result": parsed}


def _row(db_path: Path, job_id: str) -> dict[str, Any] | None:
    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
    finally:
        conn.close()
    return row if isinstance(row, dict) else None
