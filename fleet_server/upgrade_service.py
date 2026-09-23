"""Admin upgrade orchestration: lifecycle wait, git pull, apt signal."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fleet_server import install_channel, package_upgrade, self_update, upgrade_coordinator


def _defaults_for_mode(mode: str) -> tuple[int, str]:
    if mode == "update":
        return 10, "abort"
    return 45, "abort"


def run_upgrade(
    repo_root: Path,
    data_dir: Path,
    db_path: Path,
    body: dict[str, Any] | None,
    *,
    schedule_restart_fn,
) -> dict[str, Any]:
    raw = dict(body or {})
    mode = str(raw.get("mode") or "upgrade").strip().lower()
    if mode not in ("update", "upgrade"):
        mode = "upgrade"
    max_wait, default_timeout = _defaults_for_mode(mode)
    max_wait_sec = int(raw.get("max_wait_sec") or max_wait)
    on_timeout = str(raw.get("on_timeout") or default_timeout).strip().lower()
    channel_override = str(raw.get("channel") or "").strip().lower()
    channel = channel_override or install_channel.detect_install_channel(data_dir)

    meta = upgrade_coordinator.begin_upgrade(
        {"mode": mode, "max_wait_sec": max_wait_sec, "on_timeout": on_timeout, **raw}
    )
    upgrade_id = str(meta["upgrade_id"])

    upgrade_coordinator._prepare_all(upgrade_id, {"mode": mode, "reason": "fleet_upgrade"})
    wait = upgrade_coordinator.wait_for_readiness(
        db_path,
        data_dir,
        max_wait_sec=max_wait_sec,
        on_timeout=on_timeout,
        upgrade_id=upgrade_id,
    )
    if not wait.get("ok"):
        upgrade_coordinator.fail_upgrade("upgrade_blocked")
        return {
            "ok": False,
            "error": "upgrade_blocked",
            "waiting_on": wait.get("waiting_on") or [],
            "upgrade_id": upgrade_id,
        }

    if channel in ("apt_user", "apt_system"):
        queued = package_upgrade.write_upgrade_signal(
            data_dir,
            mode=mode,
            lifecycle_ok=True,
            request_id=upgrade_id,
        )
        if not queued.get("ok"):
            upgrade_coordinator.fail_upgrade(str(queued.get("error") or "queue_failed"))
            return queued
        upgrade_coordinator.complete_phase(
            "queued",
            upgrade_id=upgrade_id,
            install_channel=channel,
            timer_active=queued.get("timer_active"),
            eta_sec=queued.get("eta_sec"),
        )
        return {
            "ok": True,
            "status": "queued",
            "upgrade_id": upgrade_id,
            "install_channel": channel,
            "poll": "/v1/admin/upgrade/status",
            "eta_sec": 60,
            "note": "Root forge-fleet-apt-upgrade.timer will apply apt within ~60s.",
        }

    if channel.startswith("git"):
        stash = bool(raw.get("stash_dirty", False))
        git_root = self_update.resolve_git_root(repo_root)
        if git_root is None:
            upgrade_coordinator.fail_upgrade("self_update_unconfigured")
            return {
                "ok": False,
                "error": "self_update_unconfigured",
                "detail": "Set FLEET_GIT_ROOT or run from a git checkout.",
            }
        if self_update.infer_install_profile(repo_root) == "system" and not channel_override:
            upgrade_coordinator.fail_upgrade("system_install_requires_root")
            return {
                "ok": False,
                "error": "system_install_requires_root",
                "install_profile": "system",
                "system_root_install_command": self_update.build_system_root_install_command(git_root),
            }
        steps, rc = self_update.run_git_steps(git_root, stash_dirty=stash)
        if rc != 0:
            upgrade_coordinator.fail_upgrade("git_failed")
            return {"ok": False, "error": "git_failed", "steps": steps}
        upgrade_coordinator.complete_phase("restarting", upgrade_id=upgrade_id)
        will_restart, note = schedule_restart_fn(git_root)
        upgrade_coordinator.finish_upgrade(upgrade_id=upgrade_id, scheduled_restart=will_restart)
        return {
            "ok": True,
            "git_root": str(git_root),
            "steps": steps,
            "scheduled_restart": will_restart,
            "note": note,
            "upgrade_id": upgrade_id,
            "reload_after_ms": 2200,
        }

    upgrade_coordinator.fail_upgrade("unknown_channel")
    return {"ok": False, "error": "unknown_channel", "install_channel": channel}


def schedule_async_upgrade(
    repo_root: Path,
    data_dir: Path,
    db_path: Path,
    body: dict[str, Any] | None,
    *,
    schedule_restart_fn,
) -> None:
    def _work() -> None:
        run_upgrade(
            repo_root,
            data_dir,
            db_path,
            body,
            schedule_restart_fn=schedule_restart_fn,
        )

    threading.Thread(target=_work, daemon=True, name="fleet-upgrade").start()


def upgrade_status(data_dir: Path) -> dict[str, Any]:
    doc = upgrade_coordinator.read_status()
    phase = str(doc.get("phase") or "idle")
    apt = package_upgrade.queue_status(data_dir)
    if phase in ("idle", "complete", "failed") and apt.get("phase") not in ("idle",):
        doc = {**doc, **apt}
    doc["install_channel"] = install_channel.detect_install_channel(data_dir)
    doc["timer_active"] = package_upgrade.timer_active()
    doc.setdefault("ok", True)
    return doc
