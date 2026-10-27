"""Run the host cursor-agent. The credential never enters the job row.

The binary is the server-configured Cursor CLI (on Granite, the installed
cursor-agent). The caller supplies the localhost credential once. It is placed
only in the child environment and removed from stored output.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from fleet_server import store

_MAX_ARGS = 32
_MAX_ARG = 4000
_DEFAULT_TIMEOUT = 180
_MAX_TIMEOUT = 300


def _absolute_executable(raw: str) -> str | None:
    if not raw or not os.path.isabs(raw):
        return None
    path = Path(raw)
    try:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    except OSError:
        return None
    return None


def configured_binary() -> str | None:
    """Return the host cursor-agent.

    ``FLEET_CURSOR_AGENT_BIN`` wins when it is set. Otherwise the Fleet host's
    standard install locations are used, including the service user's
    ``~/.local/bin/cursor-agent``.
    """
    raw = str(os.environ.get("FLEET_CURSOR_AGENT_BIN") or "").strip()
    if raw:
        return _absolute_executable(raw)
    candidates = (
        "/usr/local/bin/cursor-agent",
        "/usr/bin/cursor-agent",
        str(Path.home() / ".local" / "bin" / "cursor-agent"),
    )
    for candidate in candidates:
        found = _absolute_executable(candidate)
        if found:
            return found
    return None


def _reject(http: int, error: str) -> dict[str, Any]:
    return {"http": http, "ok": False, "error": error}


def _public_body(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key != "credential"}


def _valid_args(args: object, secret: str) -> str | None:
    if not isinstance(args, list) or not args or len(args) > _MAX_ARGS:
        return "invalid_args"
    for item in args:
        if not isinstance(item, str) or not item or len(item) > _MAX_ARG or "\x00" in item:
            return "invalid_args"
        if item == "--api-key" or item.startswith("crsr_") or (secret and secret in item):
            return "credential_in_args"
    return None


def redact(text: str, secret: str) -> str:
    cleaned = text
    if secret:
        cleaned = cleaned.replace(secret, "[redacted]")
    parts = []
    for token in cleaned.split():
        parts.append("[redacted]" if token.startswith("crsr_") else token)
    return " ".join(parts)[:8000]


def submit(db_path: Path, body: object, *, inline: bool = False) -> dict[str, Any]:
    """Queue one cursor-agent run. ``inline`` waits for the child and is for tests."""
    if not isinstance(body, dict):
        return _reject(400, "invalid_body")
    secret = body.get("credential")
    public = _public_body(body)
    if not isinstance(secret, str) or not secret.strip() or secret != secret.strip():
        return _reject(400, "credential_required")
    if secret in str(public):
        return _reject(400, "credential_in_request")
    reason = _valid_args(public.get("args"), secret)
    if reason:
        return _reject(400, reason)
    binary = configured_binary()
    if binary is None:
        return _reject(400, "cursor_cli_not_configured")
    timeout = public.get("timeout_s", _DEFAULT_TIMEOUT)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1 or timeout > _MAX_TIMEOUT:
        return _reject(400, "invalid_timeout")
    args = [str(item) for item in public["args"]]
    conn = store.connect(db_path)
    try:
        job_id = store.insert_job(
            conn,
            kind="cursor_cli",
            argv=args,
            session_id="",
            meta={"cursor_cli": True, "credential_attached": True, "timeout_s": timeout},
        )
    finally:
        conn.close()
    if inline:
        _execute(db_path, job_id, binary, args, secret, timeout)
    else:
        threading.Thread(
            target=_execute,
            args=(db_path, job_id, binary, args, secret, timeout),
            daemon=True,
        ).start()
    return {"http": 202, "ok": True, "id": job_id, "status": "queued"}


def _execute(db_path: Path, job_id: str, binary: str, args: list[str], secret: str, timeout: int) -> None:
    home = tempfile.mkdtemp(prefix="fleet-cursor-cli-")
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": home,
        "TMPDIR": home,
        "LANG": "C.UTF-8",
        "CURSOR_API_KEY": secret,
    }
    code: int | None = 1
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            [binary, *args],
            cwd=home,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        code = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        code = None
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr = (stderr + "\ntimeout").strip()
    except OSError as exc:
        stderr = type(exc).__name__
    finally:
        env["CURSOR_API_KEY"] = ""
    status = "completed" if code == 0 else "failed"
    stored_out = redact(stdout, secret)
    stored_err = redact(stderr, secret)
    secret = ""
    conn = store.connect(db_path)
    try:
        store.update_job(
            conn,
            job_id,
            status=status,
            stdout=stored_out,
            stderr=stored_err,
            exit_code=-1 if code is None else code,
        )
    finally:
        conn.close()
