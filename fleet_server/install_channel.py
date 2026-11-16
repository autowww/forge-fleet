"""Detect Fleet install channel: git_user, apt_user, git_system, apt_system."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


_APT_SOURCES_LIST = Path("/etc/apt/sources.list.d/forge-fleet.list")


def _dpkg_version(pkg: str) -> str | None:
    try:
        r = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", pkg],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    ver = (r.stdout or "").strip()
    return ver or None


def _apt_policy(pkg: str) -> dict[str, str | None]:
    """Best-effort ``apt-cache policy`` parse (no root)."""
    try:
        r = subprocess.run(
            ["apt-cache", "policy", pkg],
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return {"installed": None, "candidate": None, "raw_error": "apt_cache_failed"}
    if r.returncode != 0:
        return {"installed": None, "candidate": None, "raw_error": (r.stderr or r.stdout or "apt_cache_error").strip()}
    installed: str | None = None
    candidate: str | None = None
    for line in (r.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("Installed:"):
            parts = s.split(":", 1)[-1].strip().split()
            if parts and parts[0] not in ("(none)", "(not"):
                installed = parts[0]
        elif s.startswith("Candidate:"):
            parts = s.split(":", 1)[-1].strip().split()
            if parts and parts[0] != "(none)":
                candidate = parts[0]
    return {"installed": installed, "candidate": candidate, "raw_error": None}


def detect_install_channel(data_dir: Path | None = None) -> str:
    override = str(os.environ.get("FLEET_INSTALL_CHANNEL", "") or "").strip().lower()
    if override in ("git_user", "apt_user", "git_system", "apt_system"):
        return override
    if _dpkg_version("forge-fleet-user"):
        return "apt_user"
    if _dpkg_version("forge-fleet"):
        return "apt_system"
    git_root = str(os.environ.get("FLEET_GIT_ROOT", "") or "").strip()
    runtime = Path(__file__).resolve().parent.parent
    if git_root:
        p = Path(git_root).expanduser().resolve()
        if str(p).startswith("/opt/"):
            return "git_system"
        return "git_user"
    share = Path.home() / ".local/share/forge-fleet"
    if share.is_dir() and (share / "fleet_server").is_dir():
        return "git_user"
    if str(runtime).startswith("/opt/"):
        return "git_system"
    if (Path("/usr/lib/forge-fleet") / "fleet_server").is_dir():
        return "apt_user"
    return "git_user"


def install_channel_payload(data_dir: Path) -> dict[str, Any]:
    channel = detect_install_channel(data_dir)
    apt_user_ver = _dpkg_version("forge-fleet-user")
    apt_system_ver = _dpkg_version("forge-fleet")
    timer_active = False
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "forge-fleet-apt-upgrade.timer"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
        timer_active = (r.stdout or "").strip() == "active"
    except (OSError, subprocess.SubprocessError):
        pass
    migrate_ready = channel.startswith("apt")
    pkg = "forge-fleet-user" if channel == "apt_user" else "forge-fleet" if channel == "apt_system" else ""
    policy = _apt_policy(pkg) if pkg else {"installed": None, "candidate": None, "raw_error": None}
    apt_repo_list = _APT_SOURCES_LIST.is_file()
    recommended = "POST /v1/admin/upgrade"
    if channel == "git_user":
        recommended = "land-fleet migrate-to-apt --user"
    elif channel == "git_system":
        recommended = "land-fleet migrate-to-apt --system"
    return {
        "ok": True,
        "install_channel": channel,
        "apt_user_version": apt_user_ver,
        "apt_system_version": apt_system_ver,
        "apt_candidate_version": policy.get("candidate"),
        "apt_policy_installed": policy.get("installed"),
        "apt_repo_list_present": apt_repo_list,
        "timer_active": timer_active,
        "migration_complete": migrate_ready,
        "recommended_command": recommended,
    }
