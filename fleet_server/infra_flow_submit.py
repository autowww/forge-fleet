"""Submit infra lmeta flows as Fleet docker_argv jobs with workspace bundles."""

from __future__ import annotations

import json as _json
import secrets
import uuid
from pathlib import Path
from typing import Any

from fleet_server import infra_flows, rollout_slot, runner, store, workspace_bundle


def submit_infra_flow(
    data_dir: Path,
    db_path: Path,
    body: dict[str, Any],
) -> dict[str, Any]:
    flow_id = str(body.get("flow_id") or "").strip()
    flow_doc = body.get("flow") if isinstance(body.get("flow"), dict) else None
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}

    if flow_doc is None:
        if not flow_id:
            return {"ok": False, "error": "flow_id_or_flow_required"}
        try:
            flow_doc = infra_flows.load_infra_flow(flow_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            return {"ok": False, "error": "flow_not_found", "detail": str(exc)[:400]}

    resolved_id = str(flow_doc.get("id") or flow_id or "inline-flow")
    target = rollout_slot.resolve_rollout_target(resolved_id, inputs)
    jid = uuid.uuid4().hex

    if target is not None:
        acquired = rollout_slot.try_acquire(
            target.service_id,
            jid,
            environment=target.environment,
            holder_kind="job",
            db_path=db_path,
        )
        if not acquired.get("ok"):
            return acquired

    tar = infra_flows.build_workspace_tar_gz(flow_doc, inputs)
    token = secrets.token_hex(24)

    conn = store.connect(db_path)
    slot_held = target is not None
    try:
        placeholder_argv = ["docker", "run", "--rm", "forge-infra-agent:latest", "run", "/workspace/flow.lmeta"]
        meta: dict[str, Any] = {
            "container_class": "forge_agent",
            "workspace_upload_required": True,
            "workspace_state": "pending_upload",
            "workspace_worker_token": token,
            "workspace_profile": "generic",
            "flow_id": resolved_id,
            "infra_flow": True,
            "notify_matrix_room": str(body.get("notify_matrix_room") or ""),
        }
        if target is not None:
            meta["rollout_service_id"] = target.service_id
            meta["rollout_environment"] = target.environment
            meta["rollout_holder"] = jid

        store.insert_job(
            conn,
            kind="docker_argv",
            argv=placeholder_argv,
            session_id=str(body.get("session_id") or ""),
            meta=meta,
            job_id=jid,
        )
        argv = infra_flows.default_infra_agent_argv(job_id=jid, worker_token=token)
        conn.execute(
            "UPDATE jobs SET argv_json = ? WHERE id = ?",
            (_json.dumps(argv), jid),
        )
        conn.commit()

        prof = workspace_bundle.profile_for_meta({"workspace_profile": "generic"})
        unc, sha256_hex, err, m_ver, m_schema = workspace_bundle.extract_archive_simple(
            tar,
            data_dir=data_dir,
            job_id=jid,
            profile=prof,
            manifest_required=False,
        )
        if err:
            store.update_job(conn, jid, status="failed", stderr=f"extract_failed: {err}", exit_code=1)
            if slot_held and target is not None:
                rollout_slot.release(target.service_id, jid)
            return {"ok": False, "error": "extract_failed", "detail": err, "job_id": jid}

        store.merge_job_meta(
            conn,
            jid,
            {
                "workspace_state": "ready",
                "workspace_sha256": sha256_hex,
                "workspace_upload_bytes": len(tar),
                "workspace_uncompressed_bytes": unc,
                "workspace_manifest_files_verified": m_ver,
            },
        )
    except Exception:
        if slot_held and target is not None:
            rollout_slot.release(target.service_id, jid)
        raise
    finally:
        conn.close()

    runner.spawn(db_path, jid)
    return {
        "ok": True,
        "job_id": jid,
        "id": jid,
        "status": "queued",
        "flow_id": resolved_id,
        "service_id": target.service_id if target else None,
    }
