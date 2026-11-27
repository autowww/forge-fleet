"""Pull the ecosystem git store on the Fleet host and build clusters there."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_DEFAULT_REMOTE = "https://github.com/autowww/market-studio-ecosystems.git"
_ALLOWED_SUFFIX = "market-studio-ecosystems.git"


def store_root(data_dir: Path) -> Path:
    raw = os.environ.get("ECOSYSTEM_STORE_ROOT", "").strip()
    if raw:
        return Path(raw)
    return data_dir / "ecosystem-store"


def pull(data_dir: Path, body: dict | None = None) -> dict:
    payload = body if isinstance(body, dict) else {}
    remote = str(payload.get("remote") or os.environ.get("ECOSYSTEM_STORE_GIT_URL") or _DEFAULT_REMOTE).strip()
    root = Path(str(payload.get("root"))) if str(payload.get("root") or "").strip() else store_root(data_dir)
    if not remote.endswith(_ALLOWED_SUFFIX):
        return {"ok": False, "error": "remote must be the market-studio-ecosystems repository", "http": 400}
    root.parent.mkdir(parents=True, exist_ok=True)
    if (root / ".git").is_dir():
        command = ["git", "-C", str(root), "pull", "--ff-only"]
    else:
        command = ["git", "clone", "--origin", "origin", remote, str(root)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return {"ok": False, "error": (completed.stderr or completed.stdout)[:400], "http": 400}
    return {
        "ok": True,
        "root": str(root),
        "ecosystems": (root / "graphs" / "ecosystems" / "hierarchy.yaml").is_file(),
        "masters": (root / "graphs" / "masters" / "hierarchy.yaml").is_file(),
        "clusters": (root / "graphs" / "clusters" / "hierarchy.yaml").is_file(),
        "cluster_masters": (root / "graphs" / "cluster-masters" / "hierarchy.yaml").is_file(),
        "http": 200,
    }


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


def build_cluster(data_dir: Path, body: dict | None = None) -> dict:
    """Pull the host clone, merge the named cluster, and push that commit."""
    payload = body if isinstance(body, dict) else {}
    pulled = pull(data_dir, payload)
    if not pulled.get("ok"):
        return pulled
    root = Path(str(pulled["root"]))
    slug = str(payload.get("slug") or payload.get("name") or "").strip()
    title = str(payload.get("title") or payload.get("name") or slug).strip()
    raw_members = payload.get("members")
    if not isinstance(raw_members, list):
        raw_members = payload.get("ids")
    members = [str(item).strip() for item in raw_members] if isinstance(raw_members, list) else []
    members = [item for item in members if item]
    if not slug or not members:
        return {"ok": False, "error": "cluster name and members are required", "http": 400}
    script = root / "scoring" / "ecosystem_cluster.py"
    if not script.is_file():
        return {"ok": False, "error": "cluster builder is not in this checkout", "http": 400}
    completed = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--slug", slug, "--title", title, "--members", ",".join(members)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout or completed.stderr or "cluster build failed").strip()
        return {"ok": False, "error": detail[:400], "http": 400}
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": (completed.stdout or "cluster build returned no report")[:400], "http": 400}
    relative = [str(item) for item in report.get("paths") or [] if str(item).strip()]
    if not relative:
        return {"ok": False, "error": "cluster build wrote no files", "http": 400}
    added = _git(root, "add", "--", *relative)
    if added.returncode != 0:
        return {"ok": False, "error": (added.stderr or added.stdout)[:300], "http": 400}
    staged = _git(root, "diff", "--cached", "--quiet")
    if staged.returncode != 0:
        committed = _git(root, "commit", "-m", f"cluster {slug}")
        if committed.returncode != 0:
            return {"ok": False, "error": (committed.stderr or committed.stdout)[:300], "http": 400}
        pushed = _git(root, "push", "origin", "HEAD")
        if pushed.returncode != 0:
            return {"ok": False, "committed": True, "error": (pushed.stderr or pushed.stdout)[:300], "http": 400}
    return {
        "ok": True,
        "ecosystem_id": report.get("ecosystem_id") or "",
        "master_ok": bool(report.get("master_ok")),
        "members": report.get("members") or [],
        "stored": True,
        "http": 200,
    }
