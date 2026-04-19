"""Admin-triggered git pull + optional install script + Fleet restart (user systemd)."""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def infer_install_profile(runtime_repo_root: Path) -> str:
    """
    ``user`` — typical checkout or ``~/.local/share/forge-fleet`` install; admin UI may run
    ``update-user.sh`` and ``systemctl --user restart``.

    ``system`` — code under ``/opt/forge-fleet``; refreshing production requires
    ``sudo ./install-update.sh`` (see admin modal / ``system_root_install_command``).

    Override: ``FLEET_SELF_UPDATE_INSTALL_PROFILE=user|system``.
    """
    override = (os.environ.get("FLEET_SELF_UPDATE_INSTALL_PROFILE") or "").strip().lower()
    if override in ("user", "system"):
        return override
    s = str(runtime_repo_root.resolve())
    if s.startswith("/opt/forge-fleet"):
        return "system"
    return "user"


def build_system_root_install_command(git_root: Path) -> str:
    """One shell line: pull, submodules, then ``install-update.sh`` with ``FLEET_SRC`` set."""
    g = str(git_root.resolve())
    q = shlex.quote(g)
    return (
        f"cd {q} && git pull --ff-only && git submodule update --init --recursive && "
        f"sudo env FLEET_SRC={q} ./install-update.sh"
    )


def resolve_git_root(repo_root: Path) -> Path | None:
    """Return the git checkout used for pull/submodule/update, or None if not configured."""
    raw = str(os.environ.get("FLEET_GIT_ROOT", "") or "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        if (p / ".git").exists():
            return p
        return None
    rr = repo_root.resolve()
    if (rr / ".git").exists():
        return rr
    return None


def self_update_meta(repo_root: Path) -> dict[str, Any]:
    profile = infer_install_profile(repo_root)
    root = resolve_git_root(repo_root)
    if root is None:
        return {
            "configured": False,
            "git_root": None,
            "install_profile": profile,
            "system_root_install_command": None,
            "has_update_user_script": False,
            "has_install_user_script": False,
            "has_post_git_command": bool(str(os.environ.get("FLEET_SELF_UPDATE_POST_GIT_COMMAND", "") or "").strip()),
        }
    sys_cmd = build_system_root_install_command(root) if profile == "system" else None
    return {
        "configured": True,
        "git_root": str(root),
        "install_profile": profile,
        "system_root_install_command": sys_cmd,
        "has_update_user_script": (root / "update-user.sh").is_file(),
        "has_install_user_script": (root / "install-user.sh").is_file(),
        "has_post_git_command": bool(str(os.environ.get("FLEET_SELF_UPDATE_POST_GIT_COMMAND", "") or "").strip()),
    }


def _run_cmd(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout_s: int = 300,
    label: str | None = None,
) -> dict[str, Any]:
    step = label or argv[0]
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "step": step, "stderr": "timeout", "stdout": "", "returncode": -1}
    return {
        "ok": r.returncode == 0,
        "step": step,
        "stdout": (r.stdout or "")[-12000:],
        "stderr": (r.stderr or "")[-12000:],
        "returncode": r.returncode,
    }


def run_git_steps(git_root: Path) -> tuple[list[dict[str, Any]], int]:
    steps: list[dict[str, Any]] = []
    specs: list[tuple[str, list[str]]] = [
        ("git pull --ff-only", ["git", "-C", str(git_root), "pull", "--ff-only"]),
        ("git submodule update --init --recursive", ["git", "-C", str(git_root), "submodule", "update", "--init", "--recursive"]),
    ]
    for label, argv in specs:
        one = _run_cmd(argv, cwd=git_root, timeout_s=300, label=label)
        steps.append(one)
        if not one["ok"]:
            return steps, int(one.get("returncode") or 1)
    return steps, 0


def _schedule_shell_after_delay(
    delay_s: float,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
) -> None:
    def _work() -> None:
        time.sleep(delay_s)
        try:
            subprocess.run(
                argv,
                cwd=str(cwd),
                env=env,
                timeout=600,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=_work, daemon=True).start()


def schedule_post_git_and_restart(git_root: Path) -> tuple[bool, str]:
    """
    After successful git: run update/install script or custom command, then restart Fleet user unit.
    Returns (will_restart_service, human summary).
    """
    env = os.environ.copy()
    custom = str(os.environ.get("FLEET_SELF_UPDATE_POST_GIT_COMMAND", "") or "").strip()
    update_sh = git_root / "update-user.sh"
    install_sh = git_root / "install-user.sh"

    if custom:
        _schedule_shell_after_delay(
            0.75,
            ["bash", "-lc", custom],
            cwd=git_root,
            env=env,
        )
        return True, "Scheduled custom post-git command (FLEET_SELF_UPDATE_POST_GIT_COMMAND)."

    if update_sh.is_file():
        _schedule_shell_after_delay(0.75, ["bash", str(update_sh)], cwd=git_root, env=env)
        return True, "Scheduled update-user.sh (rsync + systemd --user restart)."

    if install_sh.is_file():
        _schedule_shell_after_delay(0.75, ["bash", str(install_sh)], cwd=git_root, env=env)
        return True, "Scheduled install-user.sh (rsync + systemd --user restart)."

    def _restart_only() -> None:
        time.sleep(0.75)
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "forge-fleet.service"],
                env=env,
                timeout=60,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    threading.Thread(target=_restart_only, daemon=True).start()
    return (
        True,
        "No update-user.sh in git root — scheduled systemd --user restart only "
        "(set FLEET_GIT_ROOT to your clone, or add FLEET_SELF_UPDATE_POST_GIT_COMMAND).",
    )


def run_git_self_update(repo_root: Path) -> dict[str, Any]:
    git_root = resolve_git_root(repo_root)
    if git_root is None:
        return {
            "ok": False,
            "error": "self_update_unconfigured",
            "detail": "Set FLEET_GIT_ROOT to a git checkout (with .git), or run Fleet from a clone that includes .git.",
        }
    if infer_install_profile(repo_root) == "system":
        return {
            "ok": False,
            "error": "system_install_requires_root",
            "detail": "Fleet is installed system-wide (e.g. under /opt). Run install-update.sh as root on the host — see admin UI for a copy-paste command.",
            "install_profile": "system",
            "git_root": str(git_root),
            "system_root_install_command": build_system_root_install_command(git_root),
        }
    steps, rc = run_git_steps(git_root)
    if rc != 0:
        return {
            "ok": False,
            "error": "git_failed",
            "git_root": str(git_root),
            "steps": steps,
        }
    will_restart, note = schedule_post_git_and_restart(git_root)
    return {
        "ok": True,
        "git_root": str(git_root),
        "steps": steps,
        "scheduled_restart": will_restart,
        "note": note,
        "reload_after_ms": 2200,
    }
