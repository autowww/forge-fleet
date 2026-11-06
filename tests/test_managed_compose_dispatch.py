"""Mocked Compose dispatch for Fleet start and stop. Does not call a live daemon."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

from fleet_server.main import FleetHandler
from fleet_server import managed_compose_service


def _record(root: Path) -> dict:
    (root / "compose.yaml").write_text("name: forge-atlas\nservices: {}\n", encoding="utf-8")
    return {"id": "forge-atlas", "compose_root": str(root), "compose_files": []}


def test_start_targets_only_the_record_root(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, cwd, capture_output, text, timeout, env):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        seen["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(managed_compose_service.subprocess, "run", fake_run)
    out = managed_compose_service.start_for_record(_record(tmp_path))
    assert out["ok"] is True
    assert seen["cwd"] == str(tmp_path)
    assert seen["cmd"][:2] == ["docker", "compose"]
    assert "up" in seen["cmd"] and "-d" in seen["cmd"]
    assert "down" not in seen["cmd"]
    assert str(tmp_path / "compose.yaml") in seen["cmd"]
    assert seen["timeout"] == 900


def test_stop_dispatches_compose_down(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, cwd, capture_output, text, timeout, env):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(managed_compose_service.subprocess, "run", fake_run)
    out = managed_compose_service.stop_for_record(_record(tmp_path))
    assert out["ok"] is True
    assert seen["cmd"][-1] == "down"
    assert str(tmp_path) == str(Path(seen["cmd"][seen["cmd"].index("-f") + 1]).parent)


def test_start_timeout_does_not_claim_success(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0] if args else ["docker"], timeout=900)

    monkeypatch.setattr(managed_compose_service.subprocess, "run", fake_run)
    out = managed_compose_service.start_for_record(_record(tmp_path))
    assert out["ok"] is False
    assert out["error"] == "compose_up_failed"


def test_missing_compose_root_does_not_invoke_docker(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(managed_compose_service.subprocess, "run", lambda *a, **k: called.append(a))
    out = managed_compose_service.status_for_record({"id": "forge-atlas", "compose_root": str(tmp_path), "compose_files": []})
    assert out["ok"] is False
    assert out["last_error"] == "compose_yaml_missing"
    assert called == []


def test_status_reports_mocked_compose_ps(tmp_path, monkeypatch):
    (tmp_path / "compose.yaml").write_text("name: forge-atlas\nservices: {}\n", encoding="utf-8")

    def fake_run(cmd, cwd, capture_output, text, timeout, env):
        assert "ps" in cmd
        assert str(tmp_path) == cwd
        return SimpleNamespace(returncode=0, stdout='{"Name":"forge-atlas","State":"running","Health":""}\n', stderr="")

    monkeypatch.setattr(managed_compose_service.subprocess, "run", fake_run)
    out = managed_compose_service.status_for_record({"id": "forge-atlas", "compose_root": str(tmp_path), "compose_files": []})
    assert out["ok"] is True
    assert out["ps_ok"] is True
    assert out["services_running"] == 1


def test_auth_rejects_missing_bearer():
    handler = FleetHandler.__new__(FleetHandler)
    handler.headers = {}
    handler.server = SimpleNamespace(loopback_bind_skips_auth=False, expected_token="secret-token-value")
    handler._guard_auth = None
    assert FleetHandler._auth_ok(handler) is False
    handler.headers = {"Authorization": "Bearer secret-token-value"}
    assert FleetHandler._auth_ok(handler) is True
