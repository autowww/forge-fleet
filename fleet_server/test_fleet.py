"""Enqueue parallel "Test Fleet" Docker jobs and optionally publish results for Lenses Attention."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fleet_server import runner, store
from fleet_server.containers import HostCpuProbeFleetContainer


def _parse_probe_stdout(stdout: str) -> dict[str, Any] | None:
    raw = (stdout or "").strip()
    if not raw:
        return None
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        o = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    return o if isinstance(o, dict) else None


def _lenses_workspace_root() -> Path | None:
    raw = str(os.environ.get("FLEET_LENSES_WORKSPACE_ROOT") or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    return p if p.is_dir() else None


def _write_attention_file(batch_id: str, samples: list[dict[str, Any]]) -> Path | None:
    root = _lenses_workspace_root()
    if root is None:
        return None
    d = root / ".lenses-local"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    pcts = [float(s["cpu_usage_pct"]) for s in samples if s.get("cpu_usage_pct") is not None]
    med = sorted(pcts)[len(pcts) // 2] if pcts else None
    headline = (
        f"Fleet test: {len(samples)} host CPU probe(s)"
        + (f" — median {med:.1f}%" if med is not None else "")
    )
    payload: dict[str, Any] = {
        "ok": True,
        "batch_id": batch_id,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline": headline,
        "samples": samples,
        "to": "/settings/fleet",
    }
    out = d / "fleet-test-attention.json"
    try:
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(out, 0o600)
        except OSError:
            pass
        return out
    except OSError:
        return None


def _finalize_batch(db_path: Path, batch_id: str, job_ids: list[str]) -> dict[str, Any]:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        conn = store.connect(db_path)
        rows: list[dict[str, Any]] = []
        try:
            for jid in job_ids:
                r = store.get_job(conn, jid)
                if r is None:
                    rows = []
                    break
                rows.append(dict(r))
        finally:
            conn.close()
        if len(rows) != len(job_ids):
            time.sleep(0.35)
            continue
        terminal = {"completed", "failed", "cancelled"}
        if any(str(r.get("status") or "").lower() not in terminal for r in rows):
            time.sleep(0.35)
            continue
        samples: list[dict[str, Any]] = []
        for r in rows:
            meta = r.get("meta") if isinstance(r.get("meta"), dict) else {}
            slot_raw = meta.get("fleet_slot")
            if isinstance(slot_raw, int):
                slot_out: Any = slot_raw
            elif isinstance(slot_raw, str) and slot_raw.isdigit():
                slot_out = int(slot_raw)
            else:
                slot_out = slot_raw
            probe = _parse_probe_stdout(str(r.get("stdout") or ""))
            samples.append(
                {
                    "job_id": r.get("id"),
                    "status": r.get("status"),
                    "exit_code": r.get("exit_code"),
                    "slot": slot_out,
                    "cpu_usage_pct": probe.get("cpu_usage_pct") if probe else None,
                    "raw_ok": bool(probe and probe.get("ok")),
                }
            )
        samples.sort(key=lambda s: (s.get("slot") is None, s.get("slot")))
        path = _write_attention_file(batch_id, samples)
        return {"ok": True, "batch_id": batch_id, "samples": samples, "attention_path": str(path) if path else None}
    return {"ok": False, "error": "timeout", "batch_id": batch_id}


def spawn_test_fleet(db_path: Path, *, count: int = 5) -> dict[str, Any]:
    """Queue ``count`` host CPU probe jobs and start a background finalizer."""
    batch_id = uuid.uuid4().hex
    n = max(1, min(int(count), 20))
    job_ids: list[str] = []
    conn = store.connect(db_path)
    try:
        for slot in range(n):
            spec = HostCpuProbeFleetContainer(slot=slot)
            argv = spec.build_argv()
            meta = {**spec.meta(), "fleet_test_batch": batch_id}
            jid = store.insert_job(
                conn,
                kind="docker_argv",
                argv=argv,
                session_id=f"test-fleet-{batch_id}",
                meta=meta,
            )
            job_ids.append(jid)
            runner.spawn(db_path, jid)
    finally:
        conn.close()

    def run() -> None:
        _finalize_batch(db_path, batch_id, job_ids)

    threading.Thread(target=run, name=f"fleet-test-{batch_id[:8]}", daemon=True).start()
    return {
        "ok": True,
        "batch_id": batch_id,
        "job_ids": job_ids,
        "count": n,
        "lenses_attention": bool(_lenses_workspace_root()),
    }
