"""``docker_argv`` templates for Fleet migration step kinds (GW-2 stubs)."""

from __future__ import annotations

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


def build_argv_for_step(
    kind: str,
    *,
    migration_id: str,
    step_id: str,
    bundle_extracted: Path | None,
    meta: dict[str, Any] | None = None,
) -> list[str]:
    """
    Build a ``docker run`` argv list for a migration step.

    Stubs are shell scripts under ``fleet_server/migration_stubs/`` mounted read-only.
    """
    k = str(kind or "").strip().lower()
    if k not in STEP_KINDS:
        raise ValueError(f"unknown_migration_step_kind:{k}")
    script = _stub_script_host_path(k)
    if not script.is_file():
        raise FileNotFoundError(f"migration_stub_missing:{script}")
    image = _stub_image()
    argv: list[str] = [
        "docker",
        "run",
        "--rm",
        "-e",
        f"FLEET_MIGRATION_ID={migration_id}",
        "-e",
        f"FLEET_MIGRATION_STEP_ID={step_id}",
        "-e",
        f"FLEET_MIGRATION_STEP_KIND={k}",
        "-v",
        f"{script.resolve()}:/migration/stub.sh:ro",
    ]
    if bundle_extracted is not None and bundle_extracted.is_dir():
        argv.extend(["-v", f"{bundle_extracted.resolve()}:/migration/bundle:ro"])
    extra = meta if isinstance(meta, dict) else {}
    for key in ("service_id", "image_tag", "route_host", "volume_name"):
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
