"""Detect Fleet install channel: git_user, apt_user, git_system, apt_system."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


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
        "timer_active": timer_active,
        "migration_complete": migrate_ready,
        "recommended_command": recommended,
    }
