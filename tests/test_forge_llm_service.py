"""Tests for forge-llm compose helpers (argv + per-service records)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from fleet_server import forge_llm_service as fls


def test_resolve_compose_files(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "compose.cpu.yaml").write_text("y", encoding="utf-8")
    assert fls.resolve_compose_files(tmp_path, []) == ["compose.yaml"]
    assert fls.resolve_compose_files(tmp_path, ["compose.cpu.yaml"]) == ["compose.yaml", "compose.cpu.yaml"]


def test_resolve_rejects_unknown_file(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="compose_file_not_allowed"):
        fls.resolve_compose_files(tmp_path, ["../../etc/passwd"])


def test_compose_argv_paths(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    argv = fls._compose_argv(tmp_path, ["compose.yaml"])
    assert argv[:3] == ["docker", "compose", "-f"]
    assert argv[3] == str((tmp_path / "compose.yaml").resolve())


def test_summarize_rows() -> None:
    rows = [
        {"Name": "a", "State": "running", "Health": "healthy"},
        {"Name": "b", "State": "exited", "Health": ""},
    ]
    s = fls._summarize_rows(rows)
    assert s["services_total"] == 2
    assert s["services_running"] == 1


def test_status_for_record(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    rec = {"id": "t1", "compose_root": str(tmp_path), "compose_files": []}
    line = json.dumps({"Name": "x", "State": "running"})
    cp = subprocess.CompletedProcess(args=[], returncode=0, stdout=line + "\n", stderr="")
    with patch("fleet_server.forge_llm_service.subprocess.run", return_value=cp):
        st = fls.status_for_record(rec)
    assert st["ok"] is True
    assert st["service_id"] == "t1"
    assert st["ps_ok"] is True


def test_start_for_record_mock(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("x", encoding="utf-8")
    rec = {"id": "t1", "compose_root": str(tmp_path), "compose_files": []}

    def fake_run(*_a: object, **_k: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok\n", stderr="")

    with patch("fleet_server.forge_llm_service.subprocess.run", side_effect=fake_run):
        out = fls.start_for_record(rec)
    assert out["ok"] is True
