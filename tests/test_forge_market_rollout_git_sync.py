"""Rollout git sync must not silently build a stale forge-market tree.

Regression: Granite's checkout sat on a detached HEAD, so ``git pull --ff-only``
failed with "You are not currently on a branch". The rollout logged a warning
and built the image from the stale tree anyway, shipping code that raised
ImportError at request time and surfaced only as an opaque 502.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "rollout-forge-market-studio.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "--initial-branch=main", ".")
    _git(origin, "config", "user.email", "t@example.com")
    _git(origin, "config", "user.name", "t")
    (origin / "app.py").write_text("def new_symbol():\n    return 1\n", encoding="utf-8")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-m", "head commit")
    return origin


def _extract_function(body: str, name: str) -> str:
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        if line.startswith(f"{name}()"):
            end = next(i for i in range(idx + 1, len(lines)) if lines[i] == "}")
            return "\n".join(lines[idx : end + 1])
    raise AssertionError(f"{name} not found in {SCRIPT}")


def _call_sync(repo: Path, **env: str) -> subprocess.CompletedProcess:
    """Run only the git-sync functions from the rollout script."""
    body = SCRIPT.read_text(encoding="utf-8")
    harness = "\n".join(
        [
            "set -uo pipefail",
            'log() { printf "%s\\n" "$*"; }',
            *(
                _extract_function(body, name)
                for name in ("_remote_branch_at_head", "_git_pull_can_infer_ref", "_sync_git_tree")
            ),
            f'_sync_git_tree "{repo}"',
        ]
    )
    return subprocess.run(["bash", "-c", harness], capture_output=True, text=True, env={
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(repo),
        **env,
    })


@pytest.fixture()
def detached_clone(tmp_path: Path) -> tuple[Path, Path]:
    origin = _make_origin(tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True, text=True
    )
    # Simulate the stale Granite state: an older commit checked out detached.
    (clone / "app.py").write_text("def old_symbol():\n    return 0\n", encoding="utf-8")
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "t")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "local stale commit")
    sha = _git(clone, "rev-parse", "HEAD")
    _git(clone, "checkout", "--detach", sha)
    return origin, clone


def test_plain_git_pull_fails_on_detached_head(detached_clone) -> None:
    """Documents the failure mode the fix has to absorb."""
    _origin, clone = detached_clone
    proc = subprocess.run(
        ["git", "-C", str(clone), "pull", "--ff-only"], capture_output=True, text=True
    )
    assert proc.returncode != 0
    assert "not currently on a branch" in (proc.stderr + proc.stdout)


def test_sync_aborts_on_detached_local_only_commit(detached_clone) -> None:
    """The Granite case: detached at a commit no origin branch points at.

    Guessing origin/HEAD here would silently roll production back to a
    divergent branch, so the rollout must stop and name the fix instead.
    """
    _origin, clone = detached_clone
    proc = _call_sync(clone)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "no origin branch points at it" in out
    assert "FORGE_MARKET_GIT_REF" in out
    # Refused, so the tree is left untouched rather than rolled back.
    assert "old_symbol" in (clone / "app.py").read_text(encoding="utf-8")


def test_sync_adopts_origin_branch_that_points_at_head(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path)
    clone = tmp_path / "clone-at-tip"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True, text=True
    )
    _git(clone, "checkout", "--detach", _git(clone, "rev-parse", "HEAD"))
    proc = _call_sync(clone)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "points at HEAD, adopting it" in out
    assert _git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "forge-market-rollout"


def test_sync_recovers_when_branch_has_no_upstream(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path)
    clone = tmp_path / "clone-nb"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True, text=True
    )
    _git(clone, "checkout", "-b", "orphan-local")
    proc = _call_sync(clone)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_explicit_git_ref_still_wins(detached_clone) -> None:
    _origin, clone = detached_clone
    proc = _call_sync(clone, FORGE_MARKET_GIT_REF="main")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "new_symbol" in (clone / "app.py").read_text(encoding="utf-8")


def _call_resolve_sha(repo: Path, **env: str) -> str:
    body = SCRIPT.read_text(encoding="utf-8")
    harness = "\n".join(
        [
            "set -uo pipefail",
            f'FORGE_MARKET_ROOT="{repo}"',
            _extract_function(body, "_resolve_git_sha12"),
            "_resolve_git_sha12",
        ]
    )
    proc = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo), **env},
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_git_sha_reflects_the_build_context_not_a_stale_env_value(tmp_path: Path) -> None:
    """A stale sha mislabels the image and makes /health report the wrong commit.

    Regression: the persisted FORGE_MARKET_GIT_SHA won over the real HEAD, so
    after deploying a new branch, /health still advertised the old commit.
    """
    origin = _make_origin(tmp_path)
    head = _git(origin, "rev-parse", "--short=12", "HEAD")
    assert _call_resolve_sha(origin, FORGE_MARKET_GIT_SHA="72d48fe44af7") == head


def test_git_sha_falls_back_to_env_without_a_checkout(tmp_path: Path) -> None:
    plain = tmp_path / "no-git"
    plain.mkdir()
    assert _call_resolve_sha(plain, FORGE_MARKET_GIT_SHA="72d48fe44af7") == "72d48fe44af7"


def test_git_sha_prefers_the_synced_source_over_the_rsync_target(tmp_path: Path) -> None:
    """The deploy root is an rsync target whose .git is excluded from the sync.

    Regression: with FORGE_MARKET_GIT_REF set, the branch is checked out in the
    fallback clone and rsync'd into FORGE_MARKET_ROOT with .git excluded, so the
    root's own .git still pointed at the previous commit and /health advertised
    a commit that was not the one running.
    """
    origin = _make_origin(tmp_path)
    stale_root = tmp_path / "deploy-root"
    subprocess.run(
        ["git", "clone", str(origin), str(stale_root)], check=True, capture_output=True, text=True
    )
    assert _call_resolve_sha(stale_root, FORGE_MARKET_SYNCED_GIT_SHA="abc123def456") == "abc123def456"


def test_stale_tree_guard_covers_the_fallback_path_too() -> None:
    body = SCRIPT.read_text(encoding="utf-8")
    assert 'log "WARN: fallback git sync failed — rsync may be stale"' not in body
    assert body.count("_sync_git_tree_or_die") >= 4


def test_rollout_refuses_stale_tree_by_default() -> None:
    body = SCRIPT.read_text(encoding="utf-8")
    assert "refusing to build a stale tree" in body
    assert "FORGE_MARKET_ALLOW_STALE_TREE" in body
    # The unconditional warn-and-continue path must be gone.
    assert 'log "WARN: forge-market git sync failed — using tree as-is"' not in body
