"""Run docker argv jobs in a background thread."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fleet_server import store

_PROCS: dict[str, subprocess.Popen[str]] = {}
_proc_lock = threading.Lock()

# systemd --user often ships a tiny PATH; Docker may live under /usr/bin or Snap paths.
_FALLBACK_PATH_PREFIX = (
    "/snap/bin:/var/lib/snapd/snap/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)


def _docker_executable() -> str:
    """Resolve ``docker`` for ``subprocess`` (override with ``FLEET_DOCKER_BIN``)."""
    override = str(os.environ.get("FLEET_DOCKER_BIN") or "").strip()
    if override:
        return override
    merged = _FALLBACK_PATH_PREFIX + os.pathsep + (os.environ.get("PATH") or "")
    found = shutil.which("docker", path=merged)
    if found:
        return found
    for p in (
        "/usr/bin/docker",
        "/bin/docker",
        "/snap/bin/docker",
        "/var/lib/snapd/snap/bin/docker",
        "/usr/local/bin/docker",
    ):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return "docker"


def _merge_path_for_subprocess(env: dict[str, str]) -> None:
    cur = (env.get("PATH") or "").strip()
    if cur:
        env["PATH"] = _FALLBACK_PATH_PREFIX + os.pathsep + cur
    else:
        env["PATH"] = _FALLBACK_PATH_PREFIX


def _resolve_argv_docker(argv: list[str]) -> list[str]:
    if not argv or str(argv[0]) != "docker":
        return argv
    out = list(argv)
    out[0] = _docker_executable()
    return out


def _extract_cid(stderr: str, cidfile: str | None) -> str | None:
    if cidfile:
        try:
            p = Path(cidfile)
            if p.is_file():
                t = p.read_text(encoding="utf-8").strip()
                if t:
                    return t
        except OSError:
            pass
    m = re.search(r"^([0-9a-f]{12,64})$", (stderr or "").strip(), re.MULTILINE | re.IGNORECASE)
    return m.group(1) if m else None


def run_job(db_path: Path, job_id: str) -> None:
    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
        if row is None or row["status"] != "queued":
            return
        store.update_job(conn, job_id, status="running", running_started=time.time())
    finally:
        conn.close()
    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
    finally:
        conn.close()
    if row is None:
        return
    argv = row["argv"]
    if not isinstance(argv, list) or not argv:
        conn = store.connect(db_path)
        try:
            store.update_job(conn, job_id, status="failed", stderr="empty argv", exit_code=1)
        finally:
            conn.close()
        return
    env = os.environ.copy()
    _merge_path_for_subprocess(env)
    argv = _resolve_argv_docker(list(argv))
    cidfile: str | None = None
    if "--cidfile" in argv:
        i = argv.index("--cidfile")
        if i + 1 < len(argv):
            cidfile = argv[i + 1]
    out, err = "", ""
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        with _proc_lock:
            _PROCS[job_id] = proc
        out, err = proc.communicate(timeout=3600)
    except Exception as ex:
        conn = store.connect(db_path)
        try:
            store.update_job(conn, job_id, status="failed", stderr=str(ex)[:8000], exit_code=1)
        finally:
            conn.close()
        return
    finally:
        with _proc_lock:
            _PROCS.pop(job_id, None)
    if proc is None:
        return
    cid = _extract_cid(err or "", cidfile)
    code = int(proc.returncode if proc.returncode is not None else 1)
    # Container exit 1 means failure (e.g. probe exception); only 0 is success.
    st = "completed" if code == 0 else "failed"
    conn = store.connect(db_path)
    try:
        store.update_job(
            conn,
            job_id,
            status=st,
            stdout=out or "",
            stderr=err or "",
            exit_code=code,
            container_id=cid,
        )
    finally:
        conn.close()


def spawn(db_path: Path, job_id: str) -> None:
    t = threading.Thread(target=run_job, args=(db_path, job_id), daemon=True)
    t.start()


def cancel(job_id: str) -> bool:
    with _proc_lock:
        p = _PROCS.get(job_id)
    if p is None:
        return False
    try:
        p.kill()
    except OSError:
        return False
    return True


_CID_RE = re.compile(r"^[0-9a-f]{12,64}$", re.I)


def dispose_container(container_id: str) -> tuple[bool, str]:
    """``docker rm -f`` for Studio-initiated teardown of long-lived agent containers."""
    cid = str(container_id or "").strip()
    if not cid or not _CID_RE.match(cid):
        return False, "invalid_container_id"
    try:
        r = subprocess.run(
            [_docker_executable(), "rm", "-f", cid],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode == 0:
            return True, (r.stdout or "").strip() or "removed"
        err = (r.stderr or r.stdout or "").strip()
        return False, err[:2000] or "docker_rm_failed"
    except (OSError, subprocess.TimeoutExpired) as ex:
        return False, str(ex)[:800]


def list_active_workers(db_path: Path) -> list[dict[str, Any]]:
    """Jobs currently executing a subprocess (read-only introspection)."""
    with _proc_lock:
        snap = list(_PROCS.items())
    out: list[dict[str, Any]] = []
    conn = store.connect(db_path)
    try:
        for jid, proc in snap:
            row = store.get_job(conn, jid)
            argv = row["argv"] if row else []
            preview = " ".join(str(x) for x in argv[:24]) if isinstance(argv, list) else ""
            if len(preview) > 280:
                preview = preview[:280] + "…"
            out.append(
                {
                    "job_id": jid,
                    "pid": proc.pid,
                    "argv_preview": preview,
                    "session_id": (row or {}).get("session_id") or "",
                }
            )
    finally:
        conn.close()
    return out
