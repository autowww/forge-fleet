"""Fleet host cleanup inventory and safe GC (rollout backups, docker cache, scratch)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fleet_server import app_gateway, docker_gc, migrations as fleet_migrations, volume_quarantine, workspace_bundle

# Marker for space_guardian tier-1 enablement.
run_tier1_targets = True

DISALLOWED_TARGET_KEYS = frozenset(
    {
        "containers",
        "volumes",
        "docker_system_prune",
        "environment_delete",
        "compose_down",
        "purge_volumes",
    }
)

_PROTECTED_NAME_PATTERNS = (
    re.compile(r"^forge-market-app(-dev)?$"),
    re.compile(r"^forge-market-postgres(-dev)?$"),
    re.compile(r"^forge-gateway$"),
    re.compile(r"^forge-matrix-"),
)


def rollout_backup_keep_count() -> int:
    raw = str(os.environ.get("FLEET_ROLLOUT_BACKUP_KEEP_COUNT") or "3").strip()
    try:
        return max(1, int(raw, 10))
    except ValueError:
        return 3


def rollout_backup_keep_days() -> float:
    raw = str(os.environ.get("FLEET_ROLLOUT_BACKUP_KEEP_DAYS") or "14").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 14.0


def backup_root_for(data_dir: Path) -> Path:
    env = str(os.environ.get("FLEET_ROLLOUT_BACKUP_ROOT") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    candidate = data_dir / "backups"
    if candidate.is_dir():
        return candidate
    return (Path.home() / ".local" / "state" / "forge-fleet" / "backups").resolve()


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _run_docker(args: list[str], timeout: float = 120.0) -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker_not_found"
    try:
        r = subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return False, str(ex)[:800]
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "docker_failed")[:800]
    return True, (r.stdout or "").strip()


def snapshot_protected_containers() -> dict[str, Any]:
    ok, out = _run_docker(
        ["ps", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.ID}}"],
    )
    protected: list[dict[str, str]] = []
    all_running: list[dict[str, str]] = []
    if ok and out:
        for line in out.splitlines():
            parts = line.split("\t", 3)
            if len(parts) < 4:
                continue
            name, image, status, cid = parts[0], parts[1], parts[2], parts[3]
            row = {"name": name, "image": image, "status": status, "id": cid}
            all_running.append(row)
            if any(p.search(name) for p in _PROTECTED_NAME_PATTERNS):
                protected.append(row)
    image_ids: set[str] = set()
    ok2, ids_out = _run_docker(["ps", "-q"])
    if ok2 and ids_out:
        for cid in ids_out.splitlines():
            cid = cid.strip()
            if not cid:
                continue
            ok3, img = _run_docker(["inspect", "--format", "{{.Image}}", cid])
            if ok3 and img:
                image_ids.add(img.strip())
    return {
        "ok": ok,
        "protected_containers": protected,
        "running_count": len(all_running),
        "running_image_ids": sorted(image_ids),
    }


def operational_integrity_check(
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    b_prot = {c["name"]: c for c in (before.get("protected_containers") or []) if isinstance(c, dict)}
    a_prot = {c["name"]: c for c in (after.get("protected_containers") or []) if isinstance(c, dict)}
    missing = sorted(set(b_prot) - set(a_prot))
    not_running: list[str] = []
    for name, row in a_prot.items():
        st = str(row.get("status") or "").lower()
        if not st.startswith("up"):
            not_running.append(name)
    b_ids = set(before.get("running_image_ids") or [])
    a_ids = set(after.get("running_image_ids") or [])
    lost_images = sorted(b_ids - a_ids)
    ok = not missing and not not_running and not lost_images
    return {
        "ok": ok,
        "missing_containers": missing,
        "not_running": not_running,
        "lost_running_image_ids": lost_images,
    }


def scan_rollout_backups(backup_root: Path) -> dict[str, Any]:
    services: dict[str, Any] = {}
    total_bytes = 0
    total_files = 0
    if not backup_root.is_dir():
        return {"backup_root": str(backup_root), "services": services, "total_bytes": 0, "total_files": 0}
    for svc_dir in sorted(backup_root.iterdir()):
        if not svc_dir.is_dir():
            continue
        dumps = sorted(svc_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
        files = []
        svc_bytes = 0
        for d in dumps:
            try:
                sz = d.stat().st_size
                mtime = d.stat().st_mtime
            except OSError:
                continue
            svc_bytes += sz
            files.append({"path": str(d), "bytes": sz, "mtime": mtime})
        services[svc_dir.name] = {"count": len(files), "bytes": svc_bytes, "files": files[:20]}
        total_bytes += svc_bytes
        total_files += len(files)
    return {
        "backup_root": str(backup_root),
        "services": services,
        "total_bytes": total_bytes,
        "total_files": total_files,
    }


def gc_rollout_backups(
    backup_root: Path,
    *,
    keep_count: int = 3,
    keep_days: float = 14.0,
    strict_keep_count: bool = True,
    service_ids: list[str] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    keep_count = max(1, int(keep_count))
    keep_days = max(1.0, float(keep_days))
    cutoff = time.time() - keep_days * 86400.0
    purged: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    bytes_freed = 0
    if not backup_root.is_dir():
        return {
            "ok": True,
            "dry_run": dry_run,
            "purged": purged,
            "kept": kept,
            "bytes_freed": 0,
            "keep_count": keep_count,
            "keep_days": keep_days,
        }
    if service_ids:
        svc_dirs = [backup_root / sid for sid in service_ids if sid]
    else:
        svc_dirs = [p for p in backup_root.iterdir() if p.is_dir()]
    for svc_dir in svc_dirs:
        if not svc_dir.is_dir():
            continue
        dumps = sorted(svc_dir.glob("*.dump"), key=lambda p: p.stat().st_mtime, reverse=True)
        for i, dump in enumerate(dumps):
            try:
                mtime = dump.stat().st_mtime
                sz = dump.stat().st_size
            except OSError:
                continue
            if i < keep_count:
                kept.append(
                    {
                        "path": str(dump),
                        "service_id": svc_dir.name,
                        "bytes": sz,
                        "reason": "within_keep_count",
                    }
                )
                continue
            if not strict_keep_count and mtime >= cutoff:
                kept.append(
                    {
                        "path": str(dump),
                        "service_id": svc_dir.name,
                        "bytes": sz,
                        "reason": "within_keep_days",
                    }
                )
                continue
            if not dry_run:
                try:
                    dump.unlink()
                except OSError as ex:
                    kept.append(
                        {
                            "path": str(dump),
                            "service_id": svc_dir.name,
                            "error": str(ex)[:200],
                        }
                    )
                    continue
            if dry_run or not dump.exists():
                bytes_freed += sz
                purged.append(
                    {
                        "path": str(dump),
                        "service_id": svc_dir.name,
                        "bytes_freed": sz,
                        "reason": "exceeds_keep_count_and_days",
                    }
                )
    return {
        "ok": True,
        "dry_run": dry_run,
        "purged": purged,
        "kept": kept,
        "bytes_freed": bytes_freed,
        "keep_count": keep_count,
        "keep_days": keep_days,
        "strict_keep_count": strict_keep_count,
    }


def docker_inventory() -> dict[str, Any]:
    if shutil.which("docker") is None:
        return {"ok": False, "error": "docker_not_found"}
    try:
        r = subprocess.run(
            ["docker", "system", "df", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"ok": False, "error": str(ex)[:800]}
    rows = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return {"ok": r.returncode == 0, "returncode": r.returncode, "lines": rows[:20]}


def gc_legacy_backup_roots(roots: list[Path], *, keep_count: int = 1, dry_run: bool = True) -> dict[str, Any]:
    purged: list[dict[str, Any]] = []
    bytes_freed = 0
    for root in roots:
        if not root.is_dir():
            continue
        files = sorted(root.rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        files = [p for p in files if p.is_file()]
        for i, path in enumerate(files):
            if i < keep_count:
                continue
            try:
                sz = path.stat().st_size
            except OSError:
                continue
            if not dry_run:
                try:
                    path.unlink()
                except OSError:
                    continue
            bytes_freed += sz
            purged.append({"path": str(path), "bytes_freed": sz})
    return {"ok": True, "dry_run": dry_run, "purged": purged, "bytes_freed": bytes_freed}


def invoke_app_gc(
    data_dir: Path,
    *,
    aggressive: bool = False,
    dry_run: bool = True,
    service_ids: list[str] | None = None,
) -> dict[str, Any]:
    import json
    import urllib.error
    import urllib.request

    from fleet_server import space_policy

    targets = service_ids or ["market-studio", "market-studio-dev"]
    results: dict[str, Any] = {}
    for sid in targets:
        gw = app_gateway.load_gateway(data_dir, sid)
        if not gw:
            results[sid] = {"ok": False, "error": "gateway_not_found"}
            continue
        upstream = str(gw.get("upstream") or "").strip().rstrip("/")
        if not upstream:
            results[sid] = {"ok": False, "error": "upstream_missing"}
            continue
        url = f"{upstream}/api/maintenance/gc"
        body = json.dumps({"dry_run": dry_run, "aggressive": aggressive}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        bearer = str(gw.get("upstream_bearer") or "").strip()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw) if raw else {}
                results[sid] = parsed if isinstance(parsed, dict) else {"ok": True}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            results[sid] = {"ok": False, "http_status": exc.code, "detail": raw[:400]}
        except (OSError, json.JSONDecodeError, TimeoutError) as ex:
            results[sid] = {"ok": False, "error": str(ex)[:200]}
    total = sum(int((v or {}).get("bytes_freed_total") or 0) for v in results.values() if isinstance(v, dict))
    return {"ok": True, "dry_run": dry_run, "aggressive": aggressive, "results": results, "bytes_freed": total}


def inventory(data_dir: Path, db_path: Path) -> dict[str, Any]:
    from fleet_server import volume_quarantine

    backup_root = backup_root_for(data_dir)
    scratch = fleet_migrations.gc_stale_migration_scratch(data_dir, db_path, dry_run=True)
    vol_sync = volume_quarantine.refresh_registry(data_dir)
    return {
        "ok": True,
        "fleet_data_dir": str(data_dir),
        "rollout_backups": scan_rollout_backups(backup_root),
        "migration_scratch": {
            "would_purge": len(scratch.get("purged") or []),
            "would_free_bytes": scratch.get("bytes_freed", 0),
            "kept": len(scratch.get("kept") or []),
        },
        "job_workspaces": {
            "path": str(data_dir / "job-workspaces"),
            "bytes": _dir_bytes(data_dir / "job-workspaces"),
        },
        "docker": docker_inventory(),
        "protected_containers": snapshot_protected_containers(),
        "volumes": {
            "orphan_candidates": vol_sync.get("candidates") or [],
            "quarantine": volume_quarantine.registry_summary(data_dir),
        },
    }


def _validate_targets(targets: dict[str, Any]) -> str | None:
    for key in targets:
        if key in DISALLOWED_TARGET_KEYS:
            return f"cleanup_target_not_allowed:{key}"
    return None


def _truthy_dry_run(body: dict[str, Any]) -> bool:
    if "dry_run" not in body:
        return True
    return str(body.get("dry_run") or "").strip().lower() in {"1", "true", "yes", "on"}


def run_cleanup(data_dir: Path, db_path: Path, body: dict[str, Any]) -> dict[str, Any]:
    targets = body.get("targets")
    if targets is None:
        return inventory(data_dir, db_path)
    if not isinstance(targets, dict):
        return {"ok": False, "error": "targets_must_be_object"}
    err = _validate_targets(targets)
    if err:
        return {"ok": False, "error": err}
    dry_run = _truthy_dry_run(body)
    preflight = snapshot_protected_containers()
    results: dict[str, Any] = {}
    bytes_freed_total = 0

    if "rollout_backups" in targets:
        rb = targets.get("rollout_backups") or {}
        if not isinstance(rb, dict):
            return {"ok": False, "error": "rollout_backups_must_be_object"}
        svc_ids = rb.get("service_ids")
        sid_list = [str(s) for s in svc_ids] if isinstance(svc_ids, list) else None
        strict_raw = rb.get("strict_keep_count")
        strict_keep = True if strict_raw is None else bool(strict_raw)
        out = gc_rollout_backups(
            backup_root_for(data_dir),
            keep_count=int(rb.get("keep_count") or rollout_backup_keep_count()),
            keep_days=float(rb.get("keep_days") or rollout_backup_keep_days()),
            strict_keep_count=strict_keep,
            service_ids=sid_list,
            dry_run=dry_run,
        )
        results["rollout_backups"] = out
        bytes_freed_total += int(out.get("bytes_freed") or 0)

    if "migration_scratch" in targets:
        ms = fleet_migrations.gc_stale_migration_scratch(data_dir, db_path, dry_run=dry_run)
        results["migration_scratch"] = ms
        bytes_freed_total += int(ms.get("bytes_freed") or 0)

    if "job_workspaces" in targets:
        jw = targets.get("job_workspaces") or {}
        max_days = float((jw.get("max_age_days") if isinstance(jw, dict) else None) or 7)
        if dry_run:
            results["job_workspaces"] = {
                "ok": True,
                "dry_run": True,
                "max_age_days": max_days,
                "note": "workspace_gc_runs_on_apply_only",
            }
        else:
            n = workspace_bundle.gc_stale_workspaces(
                data_dir, db_path, max_age_seconds=max_days * 86400.0
            )
            results["job_workspaces"] = {"ok": True, "dry_run": False, "removed": n}

    if "docker_builder" in targets:
        db_cfg = targets.get("docker_builder") or {}
        hours = float(
            (db_cfg.get("until_hours") if isinstance(db_cfg, dict) else None)
            or docker_gc.docker_builder_prune_hours()
        )
        if dry_run:
            results["docker_builder"] = {"ok": True, "dry_run": True, "would_prune_hours": hours}
        else:
            results["docker_builder"] = docker_gc.prune_docker_builder_cache(hours=hours)

    if "docker_images" in targets:
        di = targets.get("docker_images") or {}
        hours = float((di.get("until_hours") if isinstance(di, dict) else None) or 168)
        prune_unused_all = bool(di.get("prune_unused_all")) if isinstance(di, dict) else False
        prune_dangling = bool(di.get("prune_dangling", True)) if isinstance(di, dict) else True
        if dry_run:
            results["docker_images"] = {
                "ok": True,
                "dry_run": True,
                "would_prune_dangling": prune_dangling,
                "would_prune_unused_all": prune_unused_all,
                "until_hours": hours,
            }
        else:
            results["docker_images"] = docker_gc.prune_docker_images_safe(
                hours=hours,
                prune_dangling=prune_dangling,
                prune_unused_all=prune_unused_all,
                protected_image_ids=set(preflight.get("running_image_ids") or []),
            )

    if "docker_images_unused" in targets:
        diu = targets.get("docker_images_unused") or {}
        hours = float((diu.get("until_hours") if isinstance(diu, dict) else None) or 72)
        if dry_run:
            results["docker_images_unused"] = {
                "ok": True,
                "dry_run": True,
                "would_prune_unused_all": True,
                "until_hours": hours,
            }
        else:
            results["docker_images_unused"] = docker_gc.prune_docker_images_safe(
                hours=hours,
                prune_dangling=False,
                prune_unused_all=True,
                protected_image_ids=set(preflight.get("running_image_ids") or []),
            )

    if "legacy_backup_roots" in targets:
        from fleet_server import space_policy

        lbr = targets.get("legacy_backup_roots") or {}
        keep = int((lbr.get("keep_count") if isinstance(lbr, dict) else None) or 1)
        out = gc_legacy_backup_roots(space_policy.legacy_backup_roots(), keep_count=keep, dry_run=dry_run)
        results["legacy_backup_roots"] = out
        bytes_freed_total += int(out.get("bytes_freed") or 0)

    if "quarantined_volumes" in targets:
        out = volume_quarantine.gc_quarantined_volumes(data_dir, dry_run=dry_run)
        results["quarantined_volumes"] = out
        bytes_freed_total += int(out.get("bytes_freed") or 0)

    if "app_gc" in targets:
        agc = targets.get("app_gc") or {}
        aggressive = bool(agc.get("aggressive")) if isinstance(agc, dict) else False
        svc_ids = agc.get("service_ids") if isinstance(agc, dict) and isinstance(agc.get("service_ids"), list) else None
        out = invoke_app_gc(data_dir, aggressive=aggressive, dry_run=dry_run, service_ids=svc_ids)
        results["app_gc"] = out
        bytes_freed_total += int(out.get("bytes_freed") or 0)

    postflight = snapshot_protected_containers()
    integrity = operational_integrity_check(preflight, postflight)
    return {
        "ok": integrity.get("ok", True) if not dry_run else True,
        "dry_run": dry_run,
        "preflight": preflight,
        "postflight": postflight,
        "operational_integrity": integrity,
        "operational_integrity_ok": integrity.get("ok", True),
        "results": results,
        "bytes_freed_total": bytes_freed_total,
    }
