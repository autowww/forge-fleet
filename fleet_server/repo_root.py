"""Resolve on-disk Fleet roots for rollouts and deploy assets."""

from __future__ import annotations

import os
from pathlib import Path

from fleet_server.self_update import resolve_git_root

MARKET_STUDIO_ROLLOUT_SCRIPT = "scripts/rollout-forge-market-studio.sh"
LLM_ROLLOUT_SCRIPT = "scripts/rollout-forge-llm-control-plane.sh"


def runtime_package_root() -> Path:
    """Directory that contains the ``fleet_server`` package (deb, rsync, or git checkout)."""
    return Path(__file__).resolve().parent.parent


def _dedupe_candidates(candidates: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for item in candidates:
        key = str(item.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(item.resolve())
    return out


def rollout_root_candidates(runtime: Path | None = None) -> list[Path]:
    """Ordered search paths for rollout scripts and ``deploy/`` trees."""
    rt = (runtime or runtime_package_root()).resolve()
    candidates: list[Path] = [rt]
    git = resolve_git_root(rt)
    if git is not None:
        candidates.append(git)
    gr = str(os.environ.get("FLEET_GIT_ROOT") or "").strip()
    if gr:
        candidates.append(Path(gr).expanduser())
    candidates.append(Path.home() / ".local/share/forge-fleet")
    candidates.append(Path("/opt/forge-fleet"))
    candidates.append(Path("/usr/lib/forge-fleet"))
    return _dedupe_candidates(candidates)


def resolve_operational_root(*, script_relpath: str, runtime: Path | None = None) -> Path:
    """Return the first candidate root that contains ``script_relpath``."""
    for root in rollout_root_candidates(runtime):
        if (root / script_relpath).is_file():
            return root
    raise FileNotFoundError("rollout_script_missing")


def resolve_rollout_script(script_relpath: str, *, runtime: Path | None = None) -> tuple[Path, Path]:
    """Return ``(operational_root, script_path)`` for a managed rollout."""
    root = resolve_operational_root(script_relpath=script_relpath, runtime=runtime)
    return root, root / script_relpath