"""Built-in infra flow catalog and workspace packaging for /v1/flows/submit."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from typing import Any

_INFRA_FLOWS_DIR = Path(__file__).resolve().parent.parent / "infra-flows"

_FLOW_CATALOG: dict[str, dict[str, Any]] = {
    "market-studio-rollout": {
        "title": "Market Studio rollout",
        "category": "rollout",
        "file": "market-studio-rollout.lmeta",
        "description": "Backup, migrate, deploy, smoke, audit",
    },
    "market-studio-rollback": {
        "title": "Market Studio rollback",
        "category": "rollback",
        "file": "market-studio-rollback.lmeta",
        "description": "T1 digest rollback or T2 restore from backup",
    },
    "market-studio-backup": {
        "title": "Market Studio backup",
        "category": "backup",
        "file": "market-studio-backup.lmeta",
        "description": "pg_dump backup with metadata",
    },
    "market-studio-audit": {
        "title": "Market Studio audit",
        "category": "audit",
        "file": "market-studio-audit.lmeta",
        "description": "Read-only schema, table counts, smoke tests",
    },
    "environment-replicate": {
        "title": "Environment replicate",
        "category": "replicate",
        "file": "environment-replicate.lmeta",
        "description": "Replicate prod to dev/clean with confirm gate",
    },
}


def list_infra_flows() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for flow_id, meta in sorted(_FLOW_CATALOG.items()):
        out.append(
            {
                "id": flow_id,
                "title": meta.get("title"),
                "category": meta.get("category"),
                "description": meta.get("description"),
            }
        )
    return out


def load_infra_flow(flow_id: str) -> dict[str, Any]:
    fid = str(flow_id or "").strip()
    meta = _FLOW_CATALOG.get(fid)
    if meta is None:
        raise KeyError(f"unknown flow_id: {fid}")
    path = _INFRA_FLOWS_DIR / str(meta["file"])
    if not path.is_file():
        raise FileNotFoundError(str(path))
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("flow document must be a JSON object")
    return doc


def build_workspace_tar_gz(flow_doc: dict[str, Any], inputs: dict[str, Any]) -> bytes:
    """Package flow.lmeta + inputs.json + manifest for Fleet job workspace upload."""
    flow_bytes = json.dumps(flow_doc, indent=2).encode("utf-8")
    inputs_bytes = json.dumps(inputs or {}, indent=2).encode("utf-8")
    manifest_entries = {
        "flow.lmeta": hashlib.sha256(flow_bytes).hexdigest(),
        "inputs.json": hashlib.sha256(inputs_bytes).hexdigest(),
    }
    manifest_bytes = json.dumps(
        {"version": 1, "files": manifest_entries},
        indent=2,
    ).encode("utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in (
            ("flow.lmeta", flow_bytes),
            ("inputs.json", inputs_bytes),
            (".forge_workspace_manifest.json", manifest_bytes),
        ):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = int(time.time())
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def default_infra_agent_argv(
    *,
    job_id: str,
    worker_token: str,
    workspace_mount: str = "/workspace",
    image: str = "forge-infra-agent:latest",
) -> list[str]:
    return [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace_mount}:{workspace_mount}:ro",
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-e",
        f"FLEET_JOB_ID={job_id}",
        "-e",
        f"FLEET_WORKSPACE_WORKER_TOKEN={worker_token}",
        "-e",
        "FLEET_BASE_URL=http://host.docker.internal:18766",
        image,
        "run",
        f"{workspace_mount}/flow.lmeta",
        "--inputs",
        f"{workspace_mount}/inputs.json",
    ]
