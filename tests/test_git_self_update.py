"""Tests that git-self-update path uses cooperative upgrade."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fleet_server import upgrade_service


def test_run_upgrade_git_blocked(tmp_path: Path) -> None:
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    blocked = {
        "ok": False,
        "error": "upgrade_blocked",
        "waiting_on": [{"service_id": "market-studio", "stop_allowed": False}],
    }
    with patch.object(upgrade_service, "install_channel") as ic:
        ic.detect_install_channel.return_value = "git_user"
        with patch.object(upgrade_service.upgrade_coordinator, "begin_upgrade", return_value={"upgrade_id": "u1"}):
            with patch.object(upgrade_service.upgrade_coordinator, "_prepare_all"):
                with patch.object(upgrade_service.upgrade_coordinator, "wait_for_readiness", return_value=blocked):
                    with patch.object(upgrade_service.upgrade_coordinator, "fail_upgrade") as fail:
                        out = upgrade_service.run_upgrade(
                            repo_root,
                            data_dir,
                            db,
                            {"mode": "upgrade"},
                            schedule_restart_fn=lambda _g: (False, ""),
                        )
    assert out["ok"] is False
    assert out["error"] == "upgrade_blocked"
    fail.assert_called_once_with("upgrade_blocked")


def test_run_upgrade_apt_queues_signal(tmp_path: Path) -> None:
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with patch.object(upgrade_service, "install_channel") as ic:
        ic.detect_install_channel.return_value = "apt_user"
        with patch.object(upgrade_service.upgrade_coordinator, "begin_upgrade", return_value={"upgrade_id": "u2"}):
            with patch.object(upgrade_service.upgrade_coordinator, "_prepare_all"):
                with patch.object(
                    upgrade_service.upgrade_coordinator,
                    "wait_for_readiness",
                    return_value={"ok": True},
                ):
                    with patch.object(
                        upgrade_service.package_upgrade,
                        "write_upgrade_signal",
                        return_value={"ok": True, "status": "queued", "timer_active": True, "eta_sec": 60},
                    ) as write_sig:
                        with patch.object(upgrade_service.upgrade_coordinator, "complete_phase"):
                            out = upgrade_service.run_upgrade(
                                repo_root,
                                data_dir,
                                db,
                                {"mode": "upgrade"},
                                schedule_restart_fn=MagicMock(),
                            )
    assert out["ok"] is True
    assert out["status"] == "queued"
    write_sig.assert_called_once()


def test_git_self_update_body_apt_omits_git_channel(tmp_path: Path) -> None:
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    with patch.object(upgrade_service, "install_channel") as ic:
        ic.detect_install_channel.return_value = "apt_system"
        body, detected = upgrade_service.git_self_update_body({"channel": "git", "stash": "true"}, data_dir)
    assert detected == "apt_system"
    assert "channel" not in body
    assert body["mode"] == "update"
    assert body["stash_dirty"] is True


def test_run_upgrade_require_apt_channel_blocks_git(tmp_path: Path) -> None:
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with patch.object(upgrade_service, "install_channel") as ic:
        ic.detect_install_channel.return_value = "git_user"
        with patch.object(upgrade_service.upgrade_coordinator, "begin_upgrade") as begin:
            with patch.object(upgrade_service.upgrade_coordinator, "_prepare_all") as prepare:
                with patch.object(upgrade_service.upgrade_coordinator, "wait_for_readiness") as wait:
                    out = upgrade_service.run_upgrade(
                        repo_root,
                        data_dir,
                        db,
                        {"mode": "upgrade", "require_apt_channel": True},
                        schedule_restart_fn=MagicMock(),
                    )
    assert out["ok"] is False
    assert out["error"] == "migrate_to_apt_required"
    # Policy rejection must not drain dependents (prepare-stop) first.
    begin.assert_not_called()
    prepare.assert_not_called()
    wait.assert_not_called()


def test_run_upgrade_require_apt_channel_git_fallback_opt_in(tmp_path: Path) -> None:
    db = tmp_path / "fleet.db"
    from fleet_server import store

    store.connect(db).close()
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with patch.object(upgrade_service, "install_channel") as ic:
        ic.detect_install_channel.return_value = "git_user"
        with patch.object(upgrade_service.upgrade_coordinator, "begin_upgrade", return_value={"upgrade_id": "u4"}):
            with patch.object(upgrade_service.upgrade_coordinator, "_prepare_all"):
                with patch.object(
                    upgrade_service.upgrade_coordinator,
                    "wait_for_readiness",
                    return_value={"ok": True},
                ):
                    with patch.object(upgrade_service.upgrade_coordinator, "complete_phase"):
                        with patch.object(upgrade_service.upgrade_coordinator, "finish_upgrade"):
                            with patch.object(upgrade_service, "self_update") as su:
                                su.resolve_git_root.return_value = repo_root
                                su.infer_install_profile.return_value = "user"
                                su.run_git_steps.return_value = ([{"cmd": "git pull", "rc": 0}], 0)
                                out = upgrade_service.run_upgrade(
                                    repo_root,
                                    data_dir,
                                    db,
                                    {
                                        "mode": "upgrade",
                                        "require_apt_channel": True,
                                        "allow_git_fallback": True,
                                    },
                                    schedule_restart_fn=lambda _g: (True, "restart scheduled"),
                                )
    assert out["ok"] is True
    assert out["channel_fallback"] == "git_user"
    assert out["scheduled_restart"] is True
    assert "migrate" in out["warning"].lower()


def test_git_self_update_body_git_user_forces_channel(tmp_path: Path) -> None:
    data_dir = tmp_path / "state"
    data_dir.mkdir()
    with patch.object(upgrade_service, "install_channel") as ic:
        ic.detect_install_channel.return_value = "git_user"
        body, detected = upgrade_service.git_self_update_body({}, data_dir)
    assert detected == "git_user"
    assert body["channel"] == "git"
