"""Fleet environment records, provisioning, replication, and lifecycle."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fleet_server import app_gateway, container_layout, env_templates, managed_compose_service as mcs, volume_ops

_ENV_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_APP_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")

_PROVISION_LOCKS: dict[str, threading.Lock] = {}
_PROVISION_LOG: list[str] = []
_PROVISION_LOG_LOCK = threading.Lock()

# Known adopt targets relative to fleet repo root (prod/dev dirs + market-studio-*)
_ADOPT_TARGETS: list[dict[str, Any]] = [
    {
        "app_id": "forge-market-studio",
        "env_id": "prod",
        "template_id": "forge_market_studio",
        "compose_rel": "deploy/forge-market-studio",
        "gateway_slug": "market-studio",
        "container_service_id": "market-studio",
    },
    {
        "app_id": "forge-market-studio",
        "env_id": "dev",
        "template_id": "forge_market_studio",
        "compose_rel": "deploy/forge-market-studio-dev",
        "gateway_slug": "market-studio-dev",
        "container_service_id": "market-studio-dev",
    },
    {
        "app_id": "forge-market-studio",
        "env_id": "clean",
        "template_id": "forge_market_studio",
        "compose_rel": "deploy/market-studio-clean",
        "gateway_slug": "market-studio-clean",
        "container_service_id": "market-studio-clean",
    },
]


def discover_adopt_targets(repo_root: Path) -> list[dict[str, Any]]:
    """Merge static targets with deploy/market-studio-* directories on disk."""
    out = list(_ADOPT_TARGETS)
    deploy = repo_root / "deploy"
    known_rels = {t["compose_rel"] for t in out}
    if deploy.is_dir():
        for child in sorted(deploy.glob("market-studio-*")):
            if not child.is_dir():
                continue
            rel = f"deploy/{child.name}"
            if rel in known_rels:
                continue
            env_id = child.name.replace("market-studio-", "", 1)
            tpl = env_templates.get_template("forge_market_studio")
            ids = env_templates.resolve_ids(tpl, env_id) if tpl else {}
            out.append(
                {
                    "app_id": "forge-market-studio",
                    "env_id": env_id,
                    "template_id": "forge_market_studio",
                    "compose_rel": rel,
                    "gateway_slug": ids.get("gateway_slug", f"market-studio-{env_id}"),
                    "container_service_id": ids.get("container_service_id", f"market-studio-{env_id}"),
                }
            )
            known_rels.add(rel)
    return out


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    line = f"[{_utc_now()}] {msg}"
    with _PROVISION_LOG_LOCK:
        _PROVISION_LOG.append(line)
        if len(_PROVISION_LOG) > 2000:
            del _PROVISION_LOG[:500]


def provision_log(*, max_lines: int = 200) -> dict[str, Any]:
    with _PROVISION_LOG_LOCK:
        lines = _PROVISION_LOG[-max_lines:]
    return {"ok": True, "log": "\n".join(lines), "line_count": len(lines)}


def environments_dir(data_dir: Path) -> Path:
    p = data_dir / "etc" / "environments"
    p.mkdir(parents=True, exist_ok=True)
    return p


def environment_file(data_dir: Path, env_record_id: str) -> Path:
    safe = str(env_record_id or "").strip()
    if "--" not in safe:
        raise ValueError("invalid_environment_id")
    return environments_dir(data_dir) / f"{safe}.json"


def make_record_id(app_id: str, env_id: str) -> str:
    return f"{app_id}--{env_id}"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def save_record(data_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    rid = str(record.get("id") or "")
    if not rid:
        raise ValueError("id_missing")
    record = dict(record)
    record["updated_at"] = _utc_now()
    if not record.get("created_at"):
        record["created_at"] = record["updated_at"]
    _write_json_atomic(environment_file(data_dir, rid), record)
    return record


def read_record(data_dir: Path, record_id: str) -> dict[str, Any] | None:
    p = environment_file(data_dir, record_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_records(data_dir: Path, *, app_id: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(environments_dir(data_dir).glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if app_id and rec.get("app_id") != app_id:
            continue
        out.append(rec)
    return out


def _loopback_port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def allocate_ports(template: dict[str, Any], env_id: str, *, used: set[int] | None = None) -> dict[str, int]:
    used = used or set()
    defaults = env_templates.default_ports_for_env(template, env_id)
    ranges = template.get("port_ranges") or {}
    out: dict[str, int] = {}
    for key, default in defaults.items():
        lo, hi = ranges.get(key, (default, default + 20))
        chosen: int | None = None
        for port in range(int(lo), int(hi) + 1):
            if port in used:
                continue
            if _loopback_port_free(port):
                chosen = port
                used.add(port)
                break
        if chosen is None and default not in used and _loopback_port_free(default):
            chosen = default
            used.add(default)
        if chosen is not None:
            out[key] = chosen
    return out


def _app_lock(app_id: str) -> threading.Lock:
    if app_id not in _PROVISION_LOCKS:
        _PROVISION_LOCKS[app_id] = threading.Lock()
    return _PROVISION_LOCKS[app_id]


def _read_dotenv_port(compose_root: Path, key: str) -> int | None:
    env_path = compose_root / ".env"
    if not env_path.is_file():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{key}="):
            try:
                return int(line.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def adopt_existing(data_dir: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Materialise records for known compose roots without modifying stacks."""
    adopted: list[dict[str, Any]] = []
    for spec in discover_adopt_targets(repo_root):
        rid = make_record_id(spec["app_id"], spec["env_id"])
        if read_record(data_dir, rid):
            continue
        compose_root = (repo_root / spec["compose_rel"]).resolve()
        if not compose_root.is_dir() or not (compose_root / "compose.yaml").is_file():
            continue
        tpl = env_templates.get_template(spec["template_id"])
        if not tpl:
            continue
        ports = env_templates.default_ports_for_env(tpl, spec["env_id"])
        app_port = _read_dotenv_port(compose_root, "FORGE_MARKET_STUDIO_HOST_PORT")
        pg_port = _read_dotenv_port(compose_root, "FORGE_MARKET_POSTGRES_HOST_PORT")
        if app_port:
            ports["app"] = app_port
        if pg_port:
            ports["postgres"] = pg_port
        volumes = env_templates.volume_names_from_template(tpl, spec["env_id"])
        ids = env_templates.resolve_ids(tpl, spec["env_id"])
        overlay = tpl.get("compose_overlay")
        compose_files = [overlay] if overlay else []
        record = {
            "schema_version": 1,
            "id": rid,
            "app_id": spec["app_id"],
            "env_id": spec["env_id"],
            "template_id": spec["template_id"],
            "compose_root": str(compose_root),
            "compose_files": compose_files,
            "container_service_id": spec["container_service_id"],
            "gateway_slug": spec["gateway_slug"],
            "type_id": tpl["type_id"],
            "label": ids["label"],
            "ports": ports,
            "volumes": volumes,
            "state": "ready",
            "state_message": "adopted",
            "seed_mode": "adopted",
            "adopted": True,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        save_record(data_dir, record)
        adopted.append(record)
        _log(f"adopted environment {rid} at {compose_root}")
    return adopted


def public_record(data_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    from fleet_server import app_deployments

    out = dict(record)
    svc_id = str(record.get("container_service_id") or "")
    if svc_id:
        dep = app_deployments.get_app_deployment(data_dir, svc_id)
        out["deployment"] = dep
    return out


def get_environment(data_dir: Path, record_id: str) -> dict[str, Any]:
    rec = read_record(data_dir, record_id)
    if not rec:
        return {"ok": False, "error": "not_found", "id": record_id}
    return {"ok": True, "environment": public_record(data_dir, rec)}


def list_environments(data_dir: Path, *, app_id: str | None = None, repo_root: Path | None = None) -> dict[str, Any]:
    if repo_root is not None:
        adopt_existing(data_dir, repo_root)
    recs = [public_record(data_dir, r) for r in list_records(data_dir, app_id=app_id)]
    return {"ok": True, "environments": recs, "count": len(recs)}


def _compose_files(record: dict[str, Any]) -> list[str]:
    return list(record.get("compose_files") or [])


def _compose_root(record: dict[str, Any]) -> Path:
    return Path(str(record["compose_root"])).resolve()


def _run_compose(record: dict[str, Any], *args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    root = _compose_root(record)
    rel = mcs.resolve_compose_files(root, _compose_files(record))
    cmd = mcs.compose_argv(root, rel) + list(args)
    return subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
        check=False,
    )


def _register_gateway(data_dir: Path, record: dict[str, Any], template: dict[str, Any]) -> None:
    ports = record.get("ports") or {}
    app_port = int(ports.get("app") or 0)
    if not app_port:
        raise ValueError("app_port_missing")
    gw = template.get("gateway", {})
    bearer_env = str(gw.get("bearer_env") or "")
    compose_root = _compose_root(record)
    bearer = app_gateway.read_dotenv_value(compose_root / ".env", bearer_env) if bearer_env else ""
    app_gateway.save_gateway(
        data_dir,
        {
            "service_id": record["gateway_slug"],
            "upstream": f"http://127.0.0.1:{app_port}",
            "inject_bearer": bool(bearer_env),
            "upstream_bearer": bearer,
            "app_bearer_env": bearer_env,
            "host_ui": False,
        },
    )


def _register_container_service(data_dir: Path, record: dict[str, Any]) -> None:
    container_layout.ensure_layout(data_dir)
    svc = {
        "version": 1,
        "id": record["container_service_id"],
        "type_id": record.get("type_id", "forge_market_studio"),
        "label": record.get("label", record["container_service_id"]),
        "compose_root": record["compose_root"],
        "compose_files": _compose_files(record),
    }
    p = container_layout.service_file(data_dir, record["container_service_id"])
    _write_json_atomic(p, svc)


def _smoke_health(record: dict[str, Any], template: dict[str, Any]) -> bool:
    port = int((record.get("ports") or {}).get("app") or 0)
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(10):
        try:
            r = subprocess.run(
                ["curl", "-fsS", url],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if r.returncode == 0 and "forge-market-studio" in (r.stdout or ""):
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    return False


def _set_state(data_dir: Path, record: dict[str, Any], state: str, message: str = "") -> dict[str, Any]:
    record["state"] = state
    record["state_message"] = message
    return save_record(data_dir, record)


def _provision_worker(
    data_dir: Path,
    repo_root: Path,
    *,
    app_id: str,
    env_id: str,
    template_id: str,
    seed: str,
    replicate_from: str | None,
    ports_override: dict[str, int] | None,
) -> None:
    rid = make_record_id(app_id, env_id)
    tpl = env_templates.get_template(template_id)
    if not tpl:
        _log(f"provision failed: unknown template {template_id}")
        return
    try:
        ids = env_templates.resolve_ids(tpl, env_id)
        ports = ports_override or allocate_ports(tpl, env_id)
        deploy_name = f"{app_id.replace('forge-', '')}-{env_id}" if env_id != "prod" else app_id.replace("forge-", "")
        if deploy_name.endswith("-prod"):
            deploy_name = deploy_name[: -len("-prod")]
        compose_dest = (repo_root / "deploy" / deploy_name).resolve()
        source_root = (repo_root / tpl["source_compose_root"]).resolve()

        record: dict[str, Any] = {
            "schema_version": 1,
            "id": rid,
            "app_id": app_id,
            "env_id": env_id,
            "template_id": template_id,
            "compose_root": str(compose_dest),
            "compose_files": [tpl["compose_overlay"]] if tpl.get("compose_overlay") else [],
            "container_service_id": ids["container_service_id"],
            "gateway_slug": ids["gateway_slug"],
            "type_id": tpl["type_id"],
            "label": ids["label"],
            "ports": ports,
            "volumes": env_templates.volume_names_from_template(tpl, env_id),
            "state": "provisioning",
            "seed_mode": seed,
            "replicate_from": replicate_from,
            "adopted": False,
            "provisioned_at": _utc_now(),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        save_record(data_dir, record)
        _log(f"provisioning {rid}: copy compose from {source_root} to {compose_dest}")

        if compose_dest.exists() and not (compose_dest / ".env").is_file():
            shutil.rmtree(compose_dest)
        if not compose_dest.exists():
            shutil.copytree(source_root, compose_dest, dirs_exist_ok=True)

        source_env = source_root / ".env.example"
        env_text = env_templates.render_env(tpl, app_id=app_id, env_id=env_id, ports=ports, source_env_path=source_env)
        (compose_dest / ".env").write_text(env_text, encoding="utf-8")
        record["compose_root"] = str(compose_dest)
        save_record(data_dir, record)

        vols = record.get("volumes") or {}
        for vname in vols.values():
            _log(f"creating volume {vname}")
            volume_ops.volume_create(vname)

        _set_state(data_dir, record, "seeding", f"seed={seed}")
        record = read_record(data_dir, rid) or record

        if seed == "replicate" and replicate_from:
            src = read_record(data_dir, replicate_from)
            if not src:
                raise ValueError(f"replicate_source_not_found:{replicate_from}")
            _log(f"stopping source {replicate_from} for volume copy")
            _run_compose(src, "stop")
            src_vols = src.get("volumes") or {}
            for key, dst_vol in vols.items():
                src_vol = src_vols.get(key)
                if src_vol and dst_vol:
                    _log(f"copying volume {src_vol} -> {dst_vol}")
                    cp = volume_ops.volume_cold_copy(src_vol, dst_vol)
                    if not cp.get("ok"):
                        raise ValueError(f"volume_copy_failed:{cp.get('error')}")
            _log(f"restarting source {replicate_from}")
            _run_compose(src, "up", "-d")

        _set_state(data_dir, record, "migrating")
        record = read_record(data_dir, rid) or record
        _log("starting postgres")
        r = _run_compose(record, "up", "-d", tpl.get("postgres_service_name", "postgres"))
        if r.returncode != 0:
            raise ValueError(f"postgres_start_failed:{(r.stderr or r.stdout)[:300]}")
        _log("running schema migrate")
        migrate_cmd = list(tpl.get("migrate_command") or [])
        r = _run_compose(record, *migrate_cmd, timeout=1800)
        if r.returncode != 0:
            raise ValueError(f"migrate_failed:{(r.stderr or r.stdout)[:300]}")

        _set_state(data_dir, record, "registering")
        record = read_record(data_dir, rid) or record
        _log("starting full stack")
        r = _run_compose(record, "up", "-d")
        if r.returncode != 0:
            raise ValueError(f"compose_up_failed:{(r.stderr or r.stdout)[:300]}")
        _register_container_service(data_dir, record)
        _register_gateway(data_dir, record, tpl)
        if not _smoke_health(record, tpl):
            raise ValueError("health_smoke_failed")
        _set_state(data_dir, record, "ready", "provisioned")
        _log(f"provision complete: {rid}")
    except Exception as exc:
        _log(f"provision failed for {rid}: {exc}")
        rec = read_record(data_dir, rid)
        if rec:
            _set_state(data_dir, rec, "failed", str(exc)[:500])


def schedule_provision(
    data_dir: Path,
    repo_root: Path,
    *,
    app_id: str,
    env_id: str,
    template_id: str,
    seed: str = "clean",
    replicate_from: str | None = None,
    ports: dict[str, int] | None = None,
) -> dict[str, Any]:
    if not _APP_ID_RE.match(app_id) or not _ENV_ID_RE.match(env_id):
        return {"ok": False, "error": "invalid_id"}
    rid = make_record_id(app_id, env_id)
    if read_record(data_dir, rid) and not read_record(data_dir, rid).get("adopted"):
        existing = read_record(data_dir, rid)
        if existing and existing.get("state") == "ready":
            return {"ok": False, "error": "already_exists", "id": rid}
    tpl = env_templates.get_template(template_id)
    if not tpl:
        return {"ok": False, "error": "template_not_found"}
    if seed == "replicate" and not replicate_from:
        return {"ok": False, "error": "replicate_from_required"}
    lock = _app_lock(app_id)
    if not lock.acquire(blocking=False):
        return {"ok": False, "error": "provisioning_in_progress", "app_id": app_id}

    def _run() -> None:
        try:
            _provision_worker(
                data_dir,
                repo_root,
                app_id=app_id,
                env_id=env_id,
                template_id=template_id,
                seed=seed,
                replicate_from=replicate_from,
                ports_override=ports,
            )
        finally:
            lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {
        "ok": True,
        "scheduled": True,
        "id": rid,
        "note": "Poll GET /v1/environments/provision-log for progress.",
    }


def replicate_environment(
    data_dir: Path,
    record_id: str,
    *,
    from_id: str,
    stop_source: bool = True,
    restart_source: bool = True,
) -> dict[str, Any]:
    rec = read_record(data_dir, record_id)
    if not rec:
        return {"ok": False, "error": "not_found"}
    src = read_record(data_dir, from_id)
    if not src:
        return {"ok": False, "error": "source_not_found"}
    tpl = env_templates.get_template(str(rec.get("template_id") or ""))
    if not tpl:
        return {"ok": False, "error": "template_not_found"}
    lock = _app_lock(str(rec.get("app_id") or ""))
    if not lock.acquire(blocking=False):
        return {"ok": False, "error": "provisioning_in_progress"}

    def _run() -> None:
        try:
            if stop_source:
                _log(f"replicate: stopping source {from_id}")
                _run_compose(src, "stop")
            src_vols = src.get("volumes") or {}
            dst_vols = rec.get("volumes") or {}
            for key, dst_vol in dst_vols.items():
                src_vol = src_vols.get(key)
                if src_vol and dst_vol:
                    _log(f"replicate: copy {src_vol} -> {dst_vol}")
                    volume_ops.volume_cold_copy(src_vol, dst_vol)
            _set_state(data_dir, rec, "migrating", "replicate")
            r = _run_compose(rec, "up", "-d")
            if r.returncode != 0:
                raise ValueError("compose_up_failed")
            migrate_cmd = list(tpl.get("migrate_command") or [])
            _run_compose(rec, *migrate_cmd, timeout=1800)
            if restart_source and stop_source:
                _run_compose(src, "up", "-d")
            _set_state(data_dir, rec, "ready", "replicated")
            _log(f"replicate complete: {record_id} from {from_id}")
        except Exception as exc:
            _log(f"replicate failed: {exc}")
            r2 = read_record(data_dir, record_id)
            if r2:
                _set_state(data_dir, r2, "failed", str(exc)[:500])
            if restart_source and stop_source:
                _run_compose(src, "up", "-d")
        finally:
            lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "scheduled": True, "id": record_id}


def start_environment(data_dir: Path, record_id: str) -> dict[str, Any]:
    rec = read_record(data_dir, record_id)
    if not rec:
        return {"ok": False, "error": "not_found"}
    r = _run_compose(rec, "up", "-d")
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "start_failed")[:500]}
    _set_state(data_dir, rec, "ready", "started")
    return {"ok": True, "id": record_id}


def stop_environment(data_dir: Path, record_id: str) -> dict[str, Any]:
    rec = read_record(data_dir, record_id)
    if not rec:
        return {"ok": False, "error": "not_found"}
    r = _run_compose(rec, "stop")
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout or "stop_failed")[:500]}
    _set_state(data_dir, rec, "stopped", "stopped")
    return {"ok": True, "id": record_id}


def delete_environment(data_dir: Path, record_id: str, *, purge_volumes: bool = False) -> dict[str, Any]:
    rec = read_record(data_dir, record_id)
    if not rec:
        return {"ok": False, "error": "not_found"}
    if rec.get("adopted"):
        return {"ok": False, "error": "cannot_delete_adopted"}
    root = _compose_root(rec)
    ps, _ = mcs.compose_ps(root, mcs.resolve_compose_files(root, _compose_files(rec)))
    running = [row for row in ps if str(row.get("State", "")).lower() == "running"]
    if running:
        return {"ok": False, "error": "environment_running", "detail": "Stop the environment first."}
    slug = str(rec.get("gateway_slug") or "")
    if slug:
        app_gateway.delete_gateway(data_dir, slug)
    svc_id = str(rec.get("container_service_id") or "")
    if svc_id:
        svc_path = container_layout.service_file(data_dir, svc_id)
        if svc_path.is_file():
            svc_path.unlink()
    if purge_volumes:
        for vname in (rec.get("volumes") or {}).values():
            volume_ops.volume_remove(vname, force=True)
    env_path = environment_file(data_dir, record_id)
    if env_path.is_file():
        env_path.unlink()
    if root.is_dir() and not rec.get("adopted"):
        shutil.rmtree(root, ignore_errors=True)
    return {"ok": True, "id": record_id, "purged_volumes": purge_volumes}
