"""Orphan Docker volume discovery and quarantine registry."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fleet_server import environments, space_policy


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def registry_path(data_dir: Path) -> Path:
    return data_dir / "space" / "quarantine.json"


def _load_registry(data_dir: Path) -> dict[str, Any]:
    path = registry_path(data_dir)
    if not path.is_file():
        return {"version": 1, "volumes": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "volumes": {}}
    if not isinstance(doc, dict):
        return {"version": 1, "volumes": {}}
    doc.setdefault("volumes", {})
    return doc


def _save_registry(data_dir: Path, doc: dict[str, Any]) -> None:
    path = registry_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _allowlist() -> set[str]:
    raw = str(os.environ.get("FLEET_VOLUME_ALLOWLIST") or "").strip()
    out: set[str] = set()
    for part in raw.split(","):
        name = part.strip()
        if name:
            out.add(name)
    return out


def _docker_json_lines(argv: list[str], timeout: float = 120.0) -> list[dict[str, Any]]:
    if shutil.which("docker") is None:
        return []
    try:
        r = subprocess.run(
            ["docker", *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[dict[str, Any]] = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _mounted_volume_names() -> set[str]:
    names: set[str] = set()
    try:
        r = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        containers = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
        for cid in containers:
            ir = subprocess.run(
                ["docker", "inspect", "-f", "{{range .Mounts}}{{.Name}} {{end}}", cid],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            for token in (ir.stdout or "").split():
                if token.strip():
                    names.add(token.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return names


def _env_volume_names(data_dir: Path) -> set[str]:
    names: set[str] = set()
    for rec in environments.list_records(data_dir):
        vols = rec.get("volumes") if isinstance(rec.get("volumes"), dict) else {}
        for v in vols.values():
            blob = str(v or "").strip()
            if blob:
                names.add(blob)
    return names


def _volume_size_bytes(name: str) -> int | None:
    rows = _docker_json_lines(["system", "df", "-v", "--format", "{{json .}}"])
    for row in rows:
        if str(row.get("Name") or "") == name:
            raw = str(row.get("Size") or row.get("RECLAIMABLE") or "")
            return _parse_docker_size(raw)
    return None


def _parse_docker_size(token: str) -> int | None:
    token = str(token or "").strip().split("(", 1)[0].strip()
    if not token or token == "0B":
        return 0
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for suffix, mult in sorted(units.items(), key=lambda x: -len(x[0])):
        if token.upper().endswith(suffix):
            try:
                return int(float(token[: -len(suffix)].strip()) * mult)
            except ValueError:
                return None
    return None


def list_all_volume_names() -> list[str]:
    names: list[str] = []
    for row in _docker_json_lines(["volume", "ls", "--format", "{{json .}}"]):
        name = str(row.get("Name") or "").strip()
        if name:
            names.append(name)
    return sorted(names)


def discover_orphan_candidates(data_dir: Path) -> list[dict[str, Any]]:
    """Volumes with no container mount and no Fleet environment record."""
    mounted = _mounted_volume_names()
    env_vols = _env_volume_names(data_dir)
    allow = _allowlist()
    orphans: list[dict[str, Any]] = []
    for name in list_all_volume_names():
        if name in mounted or name in env_vols or name in allow:
            continue
        orphans.append(
            {
                "name": name,
                "bytes": _volume_size_bytes(name),
                "reason": "no_container_no_env_record",
            }
        )
    return orphans


def refresh_registry(data_dir: Path) -> dict[str, Any]:
    """Advance quarantine registry from orphan discovery (report/sync only)."""
    doc = _load_registry(data_dir)
    volumes = doc.setdefault("volumes", {})
    now = _utc_now()
    candidates = discover_orphan_candidates(data_dir)
    seen: set[str] = set()
    for row in candidates:
        name = str(row.get("name") or "")
        if not name:
            continue
        seen.add(name)
        entry = volumes.get(name) if isinstance(volumes.get(name), dict) else {}
        if not entry:
            entry = {
                "name": name,
                "state": "candidate",
                "first_seen": now,
                "last_seen": now,
                "bytes": row.get("bytes"),
            }
        else:
            entry["last_seen"] = now
            entry["bytes"] = row.get("bytes") if row.get("bytes") is not None else entry.get("bytes")
            if entry.get("state") == "candidate":
                entry["state"] = "quarantined"
                entry.setdefault("quarantined_at", now)
        volumes[name] = entry
    for name in list(volumes.keys()):
        if name not in seen and volumes[name].get("state") not in {"deleted", "approval_required"}:
            volumes[name]["state"] = "released"
            volumes[name]["released_at"] = now
    doc["updated_at"] = now
    _save_registry(data_dir, doc)
    return {
        "ok": True,
        "candidates": candidates,
        "registry": doc,
        "quarantine_days": space_policy.volume_quarantine_days(),
    }


def registry_summary(data_dir: Path) -> dict[str, Any]:
    doc = _load_registry(data_dir)
    volumes = doc.get("volumes") if isinstance(doc.get("volumes"), dict) else {}
    active = [v for v in volumes.values() if isinstance(v, dict) and v.get("state") in {"candidate", "quarantined", "approval_required"}]
    return {
        "ok": True,
        "count": len(active),
        "volumes": active,
        "quarantine_days": space_policy.volume_quarantine_days(),
    }


def approve_volume(data_dir: Path, name: str) -> dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        return {"ok": False, "error": "volume_name_required"}
    doc = _load_registry(data_dir)
    volumes = doc.setdefault("volumes", {})
    entry = volumes.get(name)
    if not isinstance(entry, dict):
        return {"ok": False, "error": "not_quarantined", "name": name}
    entry["state"] = "approved_for_delete"
    entry["approved_at"] = _utc_now()
    volumes[name] = entry
    doc["updated_at"] = _utc_now()
    _save_registry(data_dir, doc)
    return {"ok": True, "name": name, "state": "approved_for_delete"}


def _snapshot_volume(name: str, dest: Path) -> dict[str, Any]:
    from fleet_server import volume_ops

    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = dest / f"{name}.tar"
    if shutil.which("docker") is None:
        return {"ok": False, "error": "docker_not_found"}
    script = f"tar -cf /out/{name}.tar -C /vol ."
    try:
        r = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{name}:/vol:ro",
                "-v",
                f"{dest}:/out",
                "alpine:3.20",
                "sh",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "error": str(ex)[:400]}
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "snapshot_failed")[:400]}
    try:
        sz = archive.stat().st_size
    except OSError:
        sz = 0
    return {"ok": True, "archive": str(archive), "bytes": sz}


def gc_quarantined_volumes(data_dir: Path, *, dry_run: bool = True) -> dict[str, Any]:
    from fleet_server import space_policy, volume_ops

    ready = volumes_past_ttl(data_dir)
    approved = [
        {**entry, "name": name}
        for name, entry in (_load_registry(data_dir).get("volumes") or {}).items()
        if isinstance(entry, dict) and entry.get("state") == "approved_for_delete"
    ]
    purged: list[dict[str, Any]] = []
    bytes_freed = 0
    max_gb = space_policy.volume_snapshot_max_gb()
    snap_root = data_dir / "space" / "volume-snapshots"
    doc = _load_registry(data_dir)
    volumes = doc.setdefault("volumes", {})
    for row in [*ready, *approved]:
        name = str(row.get("name") or "")
        if not name:
            continue
        entry = volumes.get(name) if isinstance(volumes.get(name), dict) else {}
        if entry.get("state") == "approval_required":
            continue
        sz = int(row.get("bytes") or 0)
        if sz > max_gb * 1024**3:
            entry["state"] = "approval_required"
            entry["approval_reason"] = "volume_exceeds_snapshot_max_gb"
            volumes[name] = entry
            continue
        if dry_run:
            purged.append({"name": name, "bytes_freed": sz, "dry_run": True})
            bytes_freed += sz
            continue
        snap = _snapshot_volume(name, snap_root)
        if not snap.get("ok"):
            purged.append({"name": name, "error": snap.get("error"), "snapshot": snap})
            continue
        rm = volume_ops.volume_remove(name, force=True)
        if rm.get("ok"):
            entry["state"] = "deleted"
            entry["deleted_at"] = _utc_now()
            entry["snapshot"] = snap.get("archive")
            volumes[name] = entry
            purged.append({"name": name, "bytes_freed": sz, "snapshot": snap.get("archive")})
            bytes_freed += sz
    doc["updated_at"] = _utc_now()
    _save_registry(data_dir, doc)
    return {"ok": True, "dry_run": dry_run, "purged": purged, "bytes_freed": bytes_freed}


def volumes_past_ttl(data_dir: Path) -> list[dict[str, Any]]:
    doc = _load_registry(data_dir)
    volumes = doc.get("volumes") if isinstance(doc.get("volumes"), dict) else {}
    ttl_days = space_policy.volume_quarantine_days()
    cutoff = time.time() - ttl_days * 86400.0
    ready: list[dict[str, Any]] = []
    for name, entry in volumes.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("state") not in {"quarantined", "approval_required"}:
            continue
        if entry.get("state") == "approval_required":
            continue
        raw = str(entry.get("quarantined_at") or entry.get("first_seen") or "")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if ts <= cutoff:
            ready.append({**entry, "name": name})
    return ready
