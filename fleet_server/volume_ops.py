"""Docker volume create, copy, and remove helpers for environment provisioning."""

from __future__ import annotations

import subprocess
from typing import Any


def volume_create(name: str) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "volume_name_missing"}
    try:
        r = subprocess.run(
            ["docker", "volume", "create", name],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:500]}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "volume_create_failed").strip()
        return {"ok": False, "error": err[:500]}
    return {"ok": True, "name": name}


def volume_remove(name: str, *, force: bool = False) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "volume_name_missing"}
    argv = ["docker", "volume", "rm"]
    if force:
        argv.append("-f")
    argv.append(name)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)[:500]}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "volume_remove_failed").strip()
        return {"ok": False, "error": err[:500]}
    return {"ok": True, "name": name}


def volume_cold_copy(source: str, dest: str, *, timeout_sec: int = 3600) -> dict[str, Any]:
    """Copy volume contents with a throwaway alpine helper (source must be stopped)."""
    source = str(source or "").strip()
    dest = str(dest or "").strip()
    if not source or not dest:
        return {"ok": False, "error": "volume_names_missing"}
    if source == dest:
        return {"ok": False, "error": "same_volume"}
    script = "rm -rf /to/* /to/.[!.]* 2>/dev/null; cp -a /from/. /to/"
    try:
        r = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{source}:/from:ro",
                "-v",
                f"{dest}:/to",
                "alpine:3.20",
                "sh",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "volume_copy_timeout"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:500]}
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "volume_copy_failed").strip()
        return {"ok": False, "error": err[:500]}
    return {"ok": True, "source": source, "dest": dest}
