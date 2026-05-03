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

from fleet_server import store, workspace_bundle

_PROCS: dict[str, subprocess.Popen[str]] = {}
_proc_lock = threading.Lock()

# systemd --user often ships a tiny PATH; Docker may live under /usr/bin or Snap paths.
_FALLBACK_PATH_PREFIX = (
    "/snap/bin:/var/lib/snapd/snap/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
)

_DOCKER_CANDIDATES = (
    "/usr/bin/docker",
    "/bin/docker",
    "/snap/bin/docker",
    "/var/lib/snapd/snap/bin/docker",
    "/usr/local/bin/docker",
    "/etc/alternatives/docker",
    "/usr/bin/docker.io",
)
_PODMAN_CANDIDATES = (
    "/usr/bin/podman",
    "/usr/local/bin/podman",
    "/bin/podman",
)


def _truthy_env(name: str) -> bool:
    v = str(os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes")


def _merged_search_path() -> str:
    return _FALLBACK_PATH_PREFIX + os.pathsep + (os.environ.get("PATH") or "")


def _first_existing_executable(paths: tuple[str, ...]) -> str | None:
    for raw in paths:
        try:
            p = Path(raw)
            if p.is_file() and os.access(p, os.X_OK):
                return str(p.resolve())
        except OSError:
            continue
    return None


def _resolve_override_bin(override: str, merged: str) -> str | None:
    """Resolve ``FLEET_DOCKER_BIN`` to an executable path (never return a bare name blindly)."""
    o = override.strip()
    if not o:
        return None
    exp = Path(o).expanduser()
    try:
        if exp.is_file() and os.access(exp, os.X_OK):
            return str(exp.resolve())
    except OSError:
        pass
    # Bare name or relative: search PATH (e.g. FLEET_DOCKER_BIN=docker → /usr/bin/docker)
    name = exp.name if "/" in o or "\\" in o else o
    found = shutil.which(name, path=merged)
    if found and os.access(found, os.X_OK):
        return found
    return None


def _docker_executable() -> str:
    """Resolve ``docker`` for ``subprocess`` (override with ``FLEET_DOCKER_BIN``).

    Falls back to **podman** when the Docker CLI is absent unless ``FLEET_NO_PODMAN_FALLBACK``
    is truthy — podman provides a compatible ``run`` for typical ``docker_argv`` workers.
    """
    merged = _merged_search_path()
    override = str(os.environ.get("FLEET_DOCKER_BIN") or "").strip()
    if override:
        got = _resolve_override_bin(override, merged)
        if got:
            return got
        # Invalid override: fall through to auto-discovery instead of returning a broken path.
    found = shutil.which("docker", path=merged)
    if found and os.access(found, os.X_OK):
        return found
    hit = _first_existing_executable(_DOCKER_CANDIDATES)
    if hit:
        return hit
    if not _truthy_env("FLEET_NO_PODMAN_FALLBACK"):
        pfound = shutil.which("podman", path=merged)
        if pfound and os.access(pfound, os.X_OK):
            return pfound
        phit = _first_existing_executable(_PODMAN_CANDIDATES)
        if phit:
            return phit
    return "docker"


def _container_cli_missing_message(resolved: str) -> str:
    return (
        f"container CLI not found or not executable ({resolved!r}). "
        "Install Docker (e.g. apt install docker.io) or Podman, add the service user to the "
        "docker group if using /var/run/docker.sock, or set FLEET_DOCKER_BIN in forge-fleet.env "
        "to the full path of docker or podman. See forge-fleet/scripts/install-docker-engine-fleet-e2e.sh."
    )


def _argv0_executable(argv: list[str]) -> bool:
    if not argv:
        return False
    p = str(argv[0])
    try:
        return bool(Path(p).is_file() and os.access(p, os.X_OK))
    except OSError:
        return False


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


def _inject_fleet_job_id_for_docker_run(argv: list[str], fleet_job_id: str) -> list[str]:
    """Insert ``-e FLEET_JOB_ID=…`` after ``docker … run`` so inner containers can reach Fleet bridge APIs."""
    jid = str(fleet_job_id or "").strip()
    if not jid or len(argv) < 3:
        return argv
    try:
        run_idx = argv.index("run")
    except ValueError:
        return argv
    pair = ["-e", f"FLEET_JOB_ID={jid}"]
    ins = run_idx + 1
    return argv[:ins] + pair + argv[ins:]


def _inject_host_metrics_client_env_for_docker_run(argv: list[str]) -> list[str]:
    """
    Optionally insert ``-e FLEET_HOST_METRICS_URL`` / ``-e FLEET_HOST_METRICS_TOKEN`` after
    the ``FLEET_JOB_ID`` pair so workloads can ``GET /v1/health`` from inside the container.

    Opt-in: ``FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER=1`` and non-empty ``FLEET_HOST_METRICS_BASE_URL``.
    Token env is only set when ``FLEET_BEARER_TOKEN`` is non-empty (copies admin bearer — security risk).
    """
    if len(argv) < 2:
        return argv
    try:
        argv.index("run")
    except ValueError:
        return argv
    if not _truthy_env("FLEET_INJECT_HOST_METRICS_ENV_IN_DOCKER"):
        return argv
    base = str(os.environ.get("FLEET_HOST_METRICS_BASE_URL") or "").strip().rstrip("/")
    if not base:
        return argv
    ins: int | None = None
    for i in range(len(argv) - 1):
        if argv[i] == "-e" and str(argv[i + 1]).startswith("FLEET_JOB_ID="):
            ins = i + 2
            break
    if ins is None:
        try:
            ins = argv.index("run") + 1
        except ValueError:
            return argv
    extra = ["-e", f"FLEET_HOST_METRICS_URL={base}"]
    tok = str(os.environ.get("FLEET_BEARER_TOKEN") or "").strip()
    if tok:
        extra.extend(["-e", f"FLEET_HOST_METRICS_TOKEN={tok}"])
    return argv[:ins] + extra + argv[ins:]


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
    data_dir = db_path.parent
    conn = store.connect(db_path)
    try:
        row = store.get_job(conn, job_id)
        if row is None or row["status"] != "queued":
            return
        meta0 = dict(row.get("meta") or {})
        if meta0.get("workspace_upload_required") and meta0.get("workspace_state") != "ready":
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
    meta = dict(row.get("meta") or {})
    cleanup_workspace = bool(
        meta.get("workspace_upload_required") and meta.get("workspace_state") == "ready"
    )
    if not isinstance(argv, list) or not argv:
        conn = store.connect(db_path)
        try:
            store.update_job(conn, job_id, status="failed", stderr="empty argv", exit_code=1)
        finally:
            conn.close()
        if cleanup_workspace:
            workspace_bundle.cleanup_job_workspace(data_dir, job_id)
        return
    env = os.environ.copy()
    _merge_path_for_subprocess(env)
    argv = _resolve_argv_docker(list(argv))
    argv = _inject_fleet_job_id_for_docker_run(argv, job_id)
    argv = _inject_host_metrics_client_env_for_docker_run(argv)
    if cleanup_workspace:
        ext = workspace_bundle.extracted_root(data_dir, job_id)
        if not ext.is_dir():
            conn = store.connect(db_path)
            try:
                store.update_job(
                    conn,
                    job_id,
                    status="failed",
                    stderr="workspace extract root missing",
                    exit_code=1,
                )
            finally:
                conn.close()
            workspace_bundle.cleanup_job_workspace(data_dir, job_id)
            return
        prof = workspace_bundle.profile_for_meta(meta)
        mount = str(prof.get("container_mount") or "/workspace")
        argv = workspace_bundle.inject_workspace_bind_mount(
            argv, host_extracted=ext, container_mount=mount
        )
    cidfile: str | None = None
    if "--cidfile" in argv:
        i = argv.index("--cidfile")
        if i + 1 < len(argv):
            cidfile = argv[i + 1]
    if not _argv0_executable(argv):
        conn = store.connect(db_path)
        try:
            store.update_job(
                conn,
                job_id,
                status="failed",
                stderr=_container_cli_missing_message(str(argv[0]) if argv else ""),
                exit_code=1,
            )
        finally:
            conn.close()
        if cleanup_workspace:
            workspace_bundle.cleanup_job_workspace(data_dir, job_id)
        return
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
        if cleanup_workspace:
            workspace_bundle.cleanup_job_workspace(data_dir, job_id)
        return
    finally:
        with _proc_lock:
            _PROCS.pop(job_id, None)
    if proc is None:
        if cleanup_workspace:
            workspace_bundle.cleanup_job_workspace(data_dir, job_id)
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
    if cleanup_workspace:
        workspace_bundle.cleanup_job_workspace(data_dir, job_id)


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
