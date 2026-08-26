"""``docker_argv`` templates for Fleet migration step kinds.

App-specific image, migrate command, DSN env name, data volume, and compose
root come from migration ``meta`` (copied from the migrator recipe). Fleet
does not hard-code product names or tool paths.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

STEP_KINDS: tuple[str, ...] = (
    "seed_corpus_volume",
    "migrate_db",
    "deploy_service",
    "register_edge_route",
    "build_image",
    "restore_from_bundle",
    "cleanup_test_migration",
)

_DEFAULT_STUB_IMAGE = "alpine:3.20"


def _stub_script_host_path(kind: str) -> Path:
    here = Path(__file__).resolve().parent / "migration_stubs"
    return here / f"{kind}.sh"


def _stub_image() -> str:
    return str(os.environ.get("FLEET_MIGRATION_STUB_IMAGE") or _DEFAULT_STUB_IMAGE).strip() or _DEFAULT_STUB_IMAGE


def _fleet_install_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _meta_str(meta: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = str(meta.get(key) or "").strip()
        if val:
            return val
    return ""


def _meta_list(meta: dict[str, Any], key: str) -> list[str]:
    raw = meta.get(key)
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return [part for part in raw.split() if part]
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
    return []


def _resolve_migrate_tool_path(bundle_extracted: Path | None, tool_name: str) -> Path | None:
    """Prefer host forge-market tools (newer fixes) over bundle-extracted copies."""
    candidates: list[Path] = []
    override_root = str(os.environ.get("FLEET_MARKET_REPO_ROOT") or "").strip()
    if override_root:
        candidates.append(Path(override_root).expanduser() / "tools" / tool_name)
    for default_root in (
        "/home/administrator/Code/forge-market",
        "/home/administrator/forge-market",
        str(Path.home() / "Code" / "forge-market"),
        str(Path.home() / "forge-market"),
    ):
        candidates.append(Path(default_root) / "tools" / tool_name)
    fleet_tools = Path(__file__).resolve().parent / "migration_tools" / tool_name
    candidates.append(fleet_tools)
    if bundle_extracted is not None:
        candidates.append(bundle_extracted / "tools" / tool_name)
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.resolve()
    return None


def _resolve_compose_root(meta: dict[str, Any]) -> Path | None:
    raw = _meta_str(meta, "compose_root", "compose_root")
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _fleet_install_root() / path
    return path.resolve()


def _dotenv_map(compose_root: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if compose_root is None:
        return out
    env_file = compose_root / ".env"
    if not env_file.is_file():
        return out
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _resolve_database_url(meta: dict[str, Any]) -> str:
    env_name = _meta_str(meta, "database_url_env") or "DATABASE_URL"
    dotenv = _dotenv_map(_resolve_compose_root(meta))
    return (
        _meta_str(meta, "database_url")
        or str(os.environ.get(env_name) or "").strip()
        or str(os.environ.get("FLEET_MIGRATION_DATABASE_URL") or "").strip()
        or str(dotenv.get(env_name) or "").strip()
        or str(dotenv.get("DATABASE_URL") or "").strip()
    )


def _common_env(migration_id: str, step_id: str, kind: str) -> list[str]:
    return [
        "-e",
        f"FLEET_MIGRATION_ID={migration_id}",
        "-e",
        f"FLEET_MIGRATION_STEP_ID={step_id}",
        "-e",
        f"FLEET_MIGRATION_STEP_KIND={kind}",
    ]


def _compose_stop_context(meta: dict[str, Any]) -> tuple[str, str, str]:
    """Return (compose_root, service_name, comma-separated compose file paths) for host stop."""
    compose_root = _resolve_compose_root(meta)
    service = _meta_str(meta, "compose_service") or "market-app"
    if compose_root is None or not compose_root.is_dir():
        return "-", "-", "-"
    files = _meta_list(meta, "compose_files") or ["compose.yaml"]
    paths = ",".join(str((compose_root / Path(name).name).resolve()) for name in files)
    return str(compose_root.resolve()), service, paths or "-"


def _build_migrate_db_argv(
    *,
    migration_id: str,
    step_id: str,
    bundle_extracted: Path | None,
    meta: dict[str, Any],
) -> list[str]:
    """Run the recipe-supplied migrate command in the recipe-supplied app image."""
    image = _meta_str(meta, "app_image") or str(os.environ.get("FLEET_MIGRATION_APP_IMAGE") or "").strip()
    command = _meta_list(meta, "migrate_argv")
    if not image:
        raise ValueError("migrate_db requires meta.app_image (from the app recipe)")
    if not command:
        raise ValueError("migrate_db requires meta.migrate_argv (from the app recipe)")
    dsn = _resolve_database_url(meta)
    if not dsn:
        raise ValueError("migrate_db requires a database URL (meta.database_url, database_url_env, or compose .env)")
    if bundle_extracted is None or not bundle_extracted.is_dir():
        raise ValueError("bundle_extracted required for migrate_db step")

    env_name = _meta_str(meta, "database_url_env") or "DATABASE_URL"
    data_volume = _meta_str(meta, "data_volume")
    data_mount = _meta_str(meta, "data_mount") or "/app/data"
    network = _meta_str(meta, "docker_network")
    app_root = str(Path(data_mount).parent or Path("/app"))

    argv: list[str] = ["docker", "run", "--rm", *_common_env(migration_id, step_id, "migrate_db")]
    argv.extend(["-e", f"{env_name}={dsn}", "-e", f"DATABASE_URL={dsn}"])
    if network:
        argv.extend(["--network", network])
    argv.extend(["-v", f"{bundle_extracted.resolve()}:/migration/bundle:ro"])
    if data_volume:
        argv.extend(["-v", f"{data_volume}:{data_mount}"])
    for tool_name in ("migrate_sqlite_to_postgres.py", "inventory_sqlite_databases.py"):
        bundled = _resolve_migrate_tool_path(bundle_extracted, tool_name)
        if bundled is not None:
            argv.extend(
                ["-v", f"{bundled}:{app_root}/tools/{tool_name}:ro"]
            )
    argv.append(image)
    argv.extend(command)

    wrapper = _stub_script_host_path("migrate_db_host")
    if not wrapper.is_file():
        return argv
    root, service, files = _compose_stop_context(meta)
    return [str(wrapper.resolve()), root, service, files, *argv]


def _build_seed_argv(
    *,
    migration_id: str,
    step_id: str,
    bundle_extracted: Path | None,
    meta: dict[str, Any],
) -> list[str]:
    volume = _meta_str(meta, "data_volume", "volume_name")
    if not volume:
        raise ValueError("seed_corpus_volume requires meta.data_volume (from the app recipe)")
    if bundle_extracted is None or not bundle_extracted.is_dir():
        raise ValueError("bundle_extracted required for seed_corpus_volume step")
    script = _stub_script_host_path("seed_corpus_volume")
    if not script.is_file():
        raise FileNotFoundError(f"migration_stub_missing:{script}")
    return [
        "docker",
        "run",
        "--rm",
        *_common_env(migration_id, step_id, "seed_corpus_volume"),
        "-e",
        f"FLEET_MIGRATION_VOLUME_NAME={volume}",
        "-v",
        f"{script.resolve()}:/migration/stub.sh:ro",
        "-v",
        f"{bundle_extracted.resolve()}:/migration/bundle:ro",
        "-v",
        f"{volume}:/seed-target",
        _stub_image(),
        "sh",
        "/migration/stub.sh",
    ]


def _build_deploy_argv(*, meta: dict[str, Any]) -> list[str]:
    compose_root = _resolve_compose_root(meta)
    if compose_root is None or not compose_root.is_dir():
        raise ValueError("deploy_service requires meta.compose_root (from the app recipe)")
    files = _meta_list(meta, "compose_files") or ["compose.yaml"]
    argv: list[str] = ["docker", "compose"]
    for name in files:
        argv.extend(["-f", str((compose_root / Path(name).name).resolve())])
    argv.extend(["--project-directory", str(compose_root), "up", "-d"])
    force = meta.get("force_recreate")
    if force is True or str(force).strip().lower() in {"1", "true", "yes"}:
        argv.append("--force-recreate")
        service = _meta_str(meta, "compose_service")
        if service:
            argv.append(service)
    return argv


def build_argv_for_step(
    kind: str,
    *,
    migration_id: str,
    step_id: str,
    bundle_extracted: Path | None,
    meta: dict[str, Any] | None = None,
) -> list[str]:
    """Build a host argv list for a migration step from recipe meta — no product defaults."""
    k = str(kind or "").strip().lower()
    if k not in STEP_KINDS:
        raise ValueError(f"unknown_migration_step_kind:{k}")
    extra = dict(meta) if isinstance(meta, dict) else {}
    if k == "migrate_db":
        return _build_migrate_db_argv(
            migration_id=migration_id,
            step_id=step_id,
            bundle_extracted=bundle_extracted,
            meta=extra,
        )
    if k == "seed_corpus_volume":
        return _build_seed_argv(
            migration_id=migration_id,
            step_id=step_id,
            bundle_extracted=bundle_extracted,
            meta=extra,
        )
    if k == "deploy_service":
        return _build_deploy_argv(meta=extra)

    script = _stub_script_host_path(k)
    if not script.is_file():
        raise FileNotFoundError(f"migration_stub_missing:{script}")
    image = _stub_image()
    argv: list[str] = [
        "docker",
        "run",
        "--rm",
        *_common_env(migration_id, step_id, k),
        "-v",
        f"{script.resolve()}:/migration/stub.sh:ro",
    ]
    if bundle_extracted is not None and bundle_extracted.is_dir():
        argv.extend(["-v", f"{bundle_extracted.resolve()}:/migration/bundle:ro"])
    for key in ("service_id", "image_tag", "route_host", "volume_name", "data_volume"):
        val = str(extra.get(key) or "").strip()
        if val:
            env_key = f"FLEET_MIGRATION_{key.upper()}"
            argv.extend(["-e", f"{env_key}={val}"])
    argv.extend([image, "sh", "/migration/stub.sh"])
    return argv


def job_meta_for_step(
    migration_id: str,
    step_id: str,
    kind: str,
    *,
    step_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Meta blob stored on the queued ``docker_argv`` job."""
    m: dict[str, Any] = {
        "container_class": "migration_step",
        "migration_id": migration_id,
        "migration_step_id": step_id,
        "migration_step_kind": str(kind),
    }
    if isinstance(step_meta, dict):
        for k, v in step_meta.items():
            if k not in m:
                m[k] = v
    return m
