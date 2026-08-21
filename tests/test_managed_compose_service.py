"""Tests for generic managed compose helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet_server import managed_compose_service as mcs


def test_resolve_compose_files(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "compose.granite.yaml").write_text("y", encoding="utf-8")
    assert mcs.resolve_compose_files(tmp_path, []) == ["compose.yaml"]
    assert mcs.resolve_compose_files(tmp_path, ["compose.granite.yaml"]) == [
        "compose.yaml",
        "compose.granite.yaml",
    ]


def test_resolve_rejects_unknown_file(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="compose_file_not_allowed"):
        mcs.resolve_compose_files(tmp_path, ["../../etc/passwd"])


def test_compose_argv_paths(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    argv = mcs.compose_argv(tmp_path, ["compose.yaml"])
    assert argv[:3] == ["docker", "compose", "-f"]
    assert argv[3] == str((tmp_path / "compose.yaml").resolve())


def test_summarize_rows() -> None:
    rows = [
        {"Name": "a", "State": "running", "Health": "healthy"},
        {"Name": "b", "State": "exited", "Health": ""},
    ]
    s = mcs._summarize_rows(rows)
    assert s["services_total"] == 2
    assert s["services_running"] == 1


def test_status_for_record(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    rec = {"id": "t1", "compose_root": str(tmp_path), "compose_files": []}
    line = json.dumps({"Name": "x", "State": "running"})
    cp = subprocess.CompletedProcess(args=[], returncode=0, stdout=line + "\n", stderr="")
    with patch("fleet_server.managed_compose_service.subprocess.run", return_value=cp):
        st = mcs.status_for_record(rec)
    assert st["ok"] is True
    assert st["service_id"] == "t1"
    assert st["ps_ok"] is True


def test_start_for_record_mock(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    rec = {"id": "t1", "compose_root": str(tmp_path), "compose_files": []}

    def fake_run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")

    with patch("fleet_server.managed_compose_service.subprocess.run", side_effect=fake_run):
        out = mcs.start_for_record(rec)
    assert out["ok"] is True


def test_market_app_host_port_from_compose_ps() -> None:
    rows = [
        {
            "Service": "market-app",
            "Ports": "127.0.0.1:19792->9792/tcp",
        }
    ]
    pub = mcs.market_app_host_port_from_compose_ps(rows)
    assert pub is not None
    assert pub["host_port"] == 19792
    assert pub["container_port"] == 9792


def test_status_includes_market_publish(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    rec = {"id": "ms", "compose_root": str(tmp_path), "compose_files": []}
    line = json.dumps(
        {"Service": "market-app", "State": "running", "Ports": "0.0.0.0:19792->9792/tcp"}
    )
    cp = subprocess.CompletedProcess(args=[], returncode=0, stdout=line + "\n", stderr="")
    with patch("fleet_server.managed_compose_service.subprocess.run", return_value=cp):
        st = mcs.status_for_record(rec)
    assert st.get("market_app_publish", {}).get("host_port") == 19792
