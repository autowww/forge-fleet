# Vendored copy of forge_certificators.worker.fleet_source_ingest — keep in sync with
# forge-certificators/src/forge_certificators/worker/fleet_source_ingest.py (stdlib only).
# The container does not pip-install forge-certificators; certificator ships ``src/`` in the
# workspace tarball (PUT …/workspace + manifest). Third-party wheels below are separate.

"""Fleet worker: fetch argv bundle from Forge Fleet, run source-ingest subprocess, report via Fleet bridge."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _http_fleet_json(
    method: str,
    url: str,
    *,
    bridge_token: str,
    body: dict[str, Any] | None = None,
    timeout_sec: float = 120.0,
) -> dict[str, Any]:
    data: bytes | None = None
    headers = {"Accept": "application/json", "X-Workspace-Worker-Token": bridge_token}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            out = json.loads(raw)
            return out if isinstance(out, dict) else {}
    except urllib.error.HTTPError as e:
        tail = ""
        try:
            tail = e.read().decode("utf-8", errors="replace")[:4000]
        except OSError:
            pass
        raise RuntimeError(f"HTTP {e.code} {tail}") from e


def _post_progress_safe(base: str, fjid: str, token: str, patch_body: dict[str, Any]) -> None:
    url = base.rstrip("/") + f"/v1/jobs/{fjid}/workspace-worker-progress"
    try:
        _http_fleet_json("POST", url, bridge_token=token, body=patch_body, timeout_sec=45.0)
    except Exception as e:
        print(f"fleet progress POST failed (non-fatal): {e}", file=sys.stderr)


def _child_env(cwd: str) -> dict[str, str]:
    e = dict(os.environ)
    root = Path(cwd)
    src = root / "src"
    if src.is_dir():
        p = str(src)
        prev = e.get("PYTHONPATH", "").strip()
        e["PYTHONPATH"] = f"{p}{os.pathsep}{prev}" if prev else p
    return e


def _artifacts_dir_from_argv(argv: list[str]) -> Path | None:
    for i, a in enumerate(argv):
        if a == "--artifacts-dir" and i + 1 < len(argv):
            return Path(argv[i + 1])
    return None


def _telemetry_message(stderr_tail: str, stdout_tail: str, *, max_len: int = 1850) -> str:
    combined = (stderr_tail or "").strip() + ("\n" if stderr_tail and stdout_tail else "") + (stdout_tail or "").strip()
    if len(combined) <= max_len:
        return combined or "Running ingest script…"
    return "…" + combined[-(max_len - 1) :]


def _run_subprocess_with_telemetry(
    *,
    base: str,
    bridge_token: str,
    fleet_job_id: str,
    argv: list[str],
    cwd: str,
    child_env: dict[str, str],
    timeout_sec: float,
) -> tuple[int, str, str]:
    """Run argv with live stderr/stdout tails POSTed to Fleet on an interval."""
    interval = float(_env("FORGE_SOURCE_INGEST_TELEMETRY_INTERVAL_SEC", "2.5") or "2.5")
    if interval < 0.5:
        interval = 0.5

    lock_err = threading.Lock()
    lock_out = threading.Lock()
    err_state = [""]
    out_state = [""]

    def reader(pipe: Any, lock: threading.Lock, state: list[str]) -> None:
        try:
            while True:
                line = pipe.readline()
                if not line:
                    break
                with lock:
                    s = state[0] + line
                    state[0] = s[-24_000:] if len(s) > 24_000 else s
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None and proc.stderr is not None
    t_err = threading.Thread(
        target=reader,
        args=(proc.stderr, lock_err, err_state),
        name="fleet-src-ingest-stderr",
        daemon=True,
    )
    t_out = threading.Thread(
        target=reader,
        args=(proc.stdout, lock_out, out_state),
        name="fleet-src-ingest-stdout",
        daemon=True,
    )
    t_err.start()
    t_out.start()

    pct = 15
    deadline = time.monotonic() + timeout_sec
    last_patch = 0.0
    try:
        while True:
            rc = proc.poll()
            now = time.monotonic()
            if rc is not None:
                break
            if now >= deadline:
                proc.kill()
                try:
                    proc.wait(timeout=30)
                except Exception:
                    pass
                with lock_err:
                    err_state[0] = (err_state[0] + "\n[fleet worker] subprocess timeout").strip()
                return 124, out_state[0], err_state[0]
            if now - last_patch >= interval:
                last_patch = now
                pct = min(88, pct + 2)
                with lock_err:
                    e = err_state[0]
                with lock_out:
                    o = out_state[0]
                msg = _telemetry_message(e, o)
                _post_progress_safe(
                    base,
                    fleet_job_id,
                    bridge_token,
                    {
                        "pct": pct,
                        "phase_label": "subprocess",
                        "message": msg,
                    },
                )
            time.sleep(0.15)
    finally:
        try:
            proc.wait(timeout=max(1.0, deadline - time.monotonic() + 60))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
        t_err.join(timeout=5)
        t_out.join(timeout=5)

    with lock_err:
        err_final = err_state[0]
    with lock_out:
        out_final = out_state[0]
    return int(proc.returncode or 0), out_final, err_final


def main() -> int:
    base = _env("FORGE_FLEET_BASE_URL")
    bridge = _env("FORGE_FLEET_WORKSPACE_WORKER_TOKEN")
    fleet_jid = _env("FLEET_JOB_ID") or _env("FORGE_FLEET_JOB_ID")

    if not base or not bridge or not fleet_jid:
        print(
            "missing FORGE_FLEET_BASE_URL, FORGE_FLEET_WORKSPACE_WORKER_TOKEN, or FLEET_JOB_ID "
            "(FLEET_JOB_ID is injected by Forge Fleet for docker_argv jobs)",
            file=sys.stderr,
        )
        return 2

    bundle_url = base.rstrip("/") + f"/v1/jobs/{fleet_jid}/workspace-worker-bundle"

    try:
        bundle = _http_fleet_json("GET", bundle_url, bridge_token=bridge, timeout_sec=120.0)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        try:
            complete_url = base.rstrip("/") + f"/v1/jobs/{fleet_jid}/workspace-worker-complete"
            _http_fleet_json(
                "POST",
                complete_url,
                bridge_token=bridge,
                body={"ok": False, "message": str(e)[:1900], "result": {}, "error": str(e)[:8000]},
                timeout_sec=120.0,
            )
        except RuntimeError:
            pass
        return 1

    argv = bundle.get("argv")
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        print("bundle argv invalid", file=sys.stderr)
        return 1
    cwd = _env("FORGE_SOURCE_INGEST_CWD") or str(bundle.get("cwd") or "").strip() or "."
    art = _artifacts_dir_from_argv(argv)
    if art is not None and not art.is_absolute():
        art = Path(cwd) / art

    _post_progress_safe(
        base,
        fleet_jid,
        bridge,
        {"pct": 10, "phase_label": "subprocess", "message": "Starting ingest…"},
    )

    try:
        rc, stdout, stderr = _run_subprocess_with_telemetry(
            base=base,
            bridge_token=bridge,
            fleet_job_id=fleet_jid,
            argv=argv,
            cwd=cwd,
            child_env=_child_env(cwd),
            timeout_sec=7200.0,
        )
    except Exception as e:
        try:
            complete_url = base.rstrip("/") + f"/v1/jobs/{fleet_jid}/workspace-worker-complete"
            _http_fleet_json(
                "POST",
                complete_url,
                bridge_token=bridge,
                body={
                    "ok": False,
                    "message": str(e)[:1900],
                    "result": {},
                    "error": str(e)[:8000],
                },
                timeout_sec=120.0,
            )
        except RuntimeError:
            pass
        print(str(e), file=sys.stderr)
        return 1

    summary: dict[str, Any] | None = None
    if art and art.is_dir():
        for p in sorted(art.glob("**/*summary*.json"), reverse=True):
            try:
                summary = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(summary, dict):
                    break
            except (OSError, json.JSONDecodeError):
                continue

    result = {
        "returncode": int(rc),
        "stdout_tail": (stdout or "")[-8000:],
        "stderr_tail": (stderr or "")[-8000:],
        "script_summary": summary,
    }
    ok = rc == 0
    complete_url = base.rstrip("/") + f"/v1/jobs/{fleet_jid}/workspace-worker-complete"
    try:
        out = _http_fleet_json(
            "POST",
            complete_url,
            bridge_token=bridge,
            body={
                "ok": ok,
                "message": "Fleet source-ingest finished" if ok else "subprocess failed",
                "result": result,
                "error": "" if ok else (stderr or stdout or "nonzero exit")[:8000],
            },
            timeout_sec=120.0,
        )
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    if not isinstance(out, dict):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
