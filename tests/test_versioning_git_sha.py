"""Git SHA resolution for /v1/version and /admin/ (FLEET_GIT_ROOT + install parity)."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from fleet_server import versioning


def test_git_sha_prefers_explicit_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FLEET_GIT_SHA", "deadbeefcafe")
    monkeypatch.setenv("SOURCE_GIT_COMMIT", "ignored_when_fleet_set")
    monkeypatch.delenv("FLEET_GIT_ROOT", raising=False)
    versioning.reset_git_sha_cache()
    assert versioning.git_sha_short() == "deadbeefcafe"


def test_git_sha_from_fleet_git_root_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-m", "m"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    short = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    monkeypatch.delenv("FLEET_GIT_SHA", raising=False)
    monkeypatch.delenv("SOURCE_GIT_COMMIT", raising=False)
    monkeypatch.setenv("FLEET_GIT_ROOT", str(repo))
    versioning.reset_git_sha_cache()
    assert versioning.git_sha_short() == short


def test_git_sha_empty_without_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bare = tmp_path / "nogit"
    bare.mkdir()
    monkeypatch.delenv("FLEET_GIT_SHA", raising=False)
    monkeypatch.delenv("SOURCE_GIT_COMMIT", raising=False)
    monkeypatch.setenv("FLEET_GIT_ROOT", str(bare))
    versioning.reset_git_sha_cache()
    assert versioning.git_sha_short() == ""


@pytest.mark.skipif(
    not (Path(versioning.__file__).resolve().parent.parent / ".git").exists(),
    reason="forge-fleet checkout has no .git (e.g. sdist unpack)",
)
def test_git_sha_falls_back_to_package_parent_when_no_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLEET_GIT_SHA", raising=False)
    monkeypatch.delenv("SOURCE_GIT_COMMIT", raising=False)
    monkeypatch.delenv("FLEET_GIT_ROOT", raising=False)
    versioning.reset_git_sha_cache()
    out = versioning.git_sha_short()
    assert len(out) >= 7
    assert all(c in "0123456789abcdef" for c in out.lower())
