"""Live presence: last-state heartbeats, local storage, and one gzipped uplink."""

from __future__ import annotations

import gzip
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from fleet_server import remote_peers

PRESENCE_SCHEMA = "forge.fleet.presence.v1"
_KINDS = frozenset({"service", "worker", "integration"})
_AUTHS = frozenset({"loopback", "bearer", "session", "mtls", "none"})
_PURPOSE_ORDER = (
    "control",
    "reasoning",
    "edge",
    "market",
    "experiments",
    "agents",
    "knowledge",
    "product",
)
_AUTH_LABELS = {
    "loopback": "loopback only",
    "bearer": "bearer",
    "session": "session",
    "mtls": "mutual TLS",
    "none": "none",
}
_TERMINAL_JOB = frozenset(
    {"succeeded", "failed", "cancelled", "canceled", "error", "complete", "completed", "killed"}
)
_UPLINK_EVERY_S = 30.0
_TICK_S = 15.0
_started = False
_started_lock = threading.Lock()


def ensure_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS presence (
            node_id TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            origin TEXT NOT NULL,
            kind TEXT NOT NULL,
            purpose TEXT NOT NULL,
            label TEXT NOT NULL,
            status TEXT NOT NULL,
            auth TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            seen_epoch REAL NOT NULL,
            ttl_s REAL NOT NULL,
            PRIMARY KEY (node_id, instance_id)
        )
        """
    )


def local_node_id() -> str:
    raw = os.environ.get("FLEET_NODE_ID", "").strip()
    return raw or socket.gethostname() or "local"


def upstream_peer_id() -> str:
    raw = os.environ.get("FLEET_UPSTREAM_PEER", "granite").strip().lower()
    if raw in {"", "none", "-", "self"}:
        return ""
    return raw


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_item(body: dict[str, Any], *, default_ttl: float = 45.0) -> dict[str, Any]:
    kind = _clip(body.get("kind") or body.get("k"), 32)
    auth = _clip(body.get("auth") or body.get("a"), 32)
    purpose = _clip(body.get("purpose") or body.get("p"), 64)
    instance_id = _clip(body.get("instance_id") or body.get("id"), 128)
    if kind not in _KINDS:
        raise ValueError("invalid_kind")
    if auth not in _AUTHS:
        raise ValueError("invalid_auth")
    if not purpose or not instance_id:
        raise ValueError("missing_fields")
    try:
        ttl = float(body.get("ttl_s") if body.get("ttl_s") is not None else body.get("ttl") or default_ttl)
    except (TypeError, ValueError):
        ttl = default_ttl
    ttl = min(max(ttl, 15.0), 600.0)
    status = _clip(body.get("status") or body.get("s") or "running", 32) or "running"
    return {
        "instance_id": instance_id,
        "kind": kind,
        "purpose": purpose,
        "label": _clip(body.get("label") or body.get("l") or instance_id, 80),
        "status": status,
        "auth": auth,
        "detail": _clip(body.get("detail") or body.get("d"), 240),
        "ttl_s": ttl,
    }


def expire(conn: Any, now: float | None = None) -> None:
    ensure_table(conn)
    conn.execute(
        "DELETE FROM presence WHERE seen_epoch + ttl_s < ?",
        (float(now if now is not None else time.time()),),
    )


def upsert_local(conn: Any, item: dict[str, Any], *, node_id: str | None = None, now: float | None = None) -> None:
    ensure_table(conn)
    nid = node_id or local_node_id()
    seen = float(now if now is not None else time.time())
    conn.execute(
        """
        INSERT INTO presence (
            node_id, instance_id, origin, kind, purpose, label, status, auth, detail, seen_epoch, ttl_s
        ) VALUES (?, ?, 'local', ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id, instance_id) DO UPDATE SET
            origin = 'local',
            kind = excluded.kind,
            purpose = excluded.purpose,
            label = excluded.label,
            status = excluded.status,
            auth = excluded.auth,
            detail = excluded.detail,
            seen_epoch = excluded.seen_epoch,
            ttl_s = excluded.ttl_s
        """,
        (
            nid,
            item["instance_id"],
            item["kind"],
            item["purpose"],
            item["label"],
            item["status"],
            item["auth"],
            item["detail"],
            seen,
            item["ttl_s"],
        ),
    )


def delete_instance(conn: Any, instance_id: str, *, node_id: str | None = None) -> None:
    ensure_table(conn)
    conn.execute(
        "DELETE FROM presence WHERE node_id = ? AND instance_id = ?",
        (node_id or local_node_id(), instance_id),
    )


def replace_aggregate(conn: Any, node_id: str, items: list[dict[str, Any]], *, now: float | None = None) -> dict[str, Any]:
    ensure_table(conn)
    nid = _clip(node_id, 128)
    if not nid:
        raise ValueError("missing_node")
    if nid == local_node_id():
        raise ValueError("aggregate_own_node")
    seen = float(now if now is not None else time.time())
    conn.execute("DELETE FROM presence WHERE node_id = ? AND origin = 'aggregate'", (nid,))
    stored = 0
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = normalize_item(raw)
        conn.execute(
            """
            INSERT INTO presence (
                node_id, instance_id, origin, kind, purpose, label, status, auth, detail, seen_epoch, ttl_s
            ) VALUES (?, ?, 'aggregate', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id, instance_id) DO UPDATE SET
                origin = 'aggregate',
                kind = excluded.kind,
                purpose = excluded.purpose,
                label = excluded.label,
                status = excluded.status,
                auth = excluded.auth,
                detail = excluded.detail,
                seen_epoch = excluded.seen_epoch,
                ttl_s = excluded.ttl_s
            """,
            (
                nid,
                item["instance_id"],
                item["kind"],
                item["purpose"],
                item["label"],
                item["status"],
                item["auth"],
                item["detail"],
                seen,
                item["ttl_s"],
            ),
        )
        stored += 1
    return {"ok": True, "node_id": nid, "stored": stored}


def _purpose_key(purpose: str) -> tuple[int, str]:
    try:
        rank = _PURPOSE_ORDER.index(purpose)
    except ValueError:
        rank = len(_PURPOSE_ORDER)
    return (rank, purpose)


def matrix(conn: Any, *, now: float | None = None) -> dict[str, Any]:
    expire(conn, now)
    rows = conn.execute(
        """
        SELECT node_id, instance_id, kind, purpose, label, status, auth, detail, seen_epoch, ttl_s
        FROM presence
        ORDER BY node_id, purpose, label
        """
    ).fetchall()
    local = local_node_id()
    node_ids: list[str] = []
    purposes: list[str] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        nid = str(row["node_id"])
        purpose = str(row["purpose"])
        if nid not in node_ids:
            node_ids.append(nid)
        if purpose not in purposes:
            purposes.append(purpose)
        inst = {
            "id": str(row["instance_id"]),
            "label": str(row["label"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "auth": str(row["auth"]),
            "auth_label": _AUTH_LABELS.get(str(row["auth"]), str(row["auth"])),
            "detail": str(row["detail"] or ""),
            "seen_epoch": float(row["seen_epoch"]),
        }
        grouped.setdefault((nid, purpose), []).append(inst)
    node_ids.sort(key=lambda n: (0 if n == local else 1, n))
    purposes.sort(key=_purpose_key)
    cells = []
    for nid in node_ids:
        for purpose in purposes:
            inst = grouped.get((nid, purpose))
            if not inst:
                continue
            cells.append({"node_id": nid, "purpose": purpose, "instances": inst})
    return {
        "ok": True,
        "schema_version": PRESENCE_SCHEMA,
        "node_id": local,
        "nodes": [{"id": n, "label": n, "local": n == local} for n in node_ids],
        "purposes": purposes,
        "cells": cells,
    }


def local_items(conn: Any) -> list[dict[str, Any]]:
    expire(conn)
    rows = conn.execute(
        """
        SELECT instance_id, kind, purpose, label, status, auth, detail, ttl_s
        FROM presence
        WHERE node_id = ? AND origin = 'local'
        """,
        (local_node_id(),),
    ).fetchall()
    return [
        {
            "id": str(r["instance_id"]),
            "kind": str(r["kind"]),
            "purpose": str(r["purpose"]),
            "label": str(r["label"]),
            "status": str(r["status"]),
            "auth": str(r["auth"]),
            "detail": str(r["detail"] or ""),
            "ttl_s": float(r["ttl_s"]),
        }
        for r in rows
    ]


def encode_aggregate(node_id: str, items: list[dict[str, Any]]) -> bytes:
    body = {"node_id": node_id, "seen_epoch": time.time(), "items": items}
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw)


def decode_aggregate(raw: bytes, *, gzipped: bool) -> dict[str, Any]:
    data = gzip.decompress(raw) if gzipped else raw
    if len(data) > 262_144:
        raise ValueError("aggregate_too_large")
    doc = json.loads(data.decode("utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("invalid_aggregate")
    return doc


def fleet_self_item() -> dict[str, Any]:
    token = os.environ.get("FLEET_BEARER_TOKEN", "").strip()
    enforce = os.environ.get("FLEET_ENFORCE_BEARER", "").strip().lower() in {"1", "true", "yes"}
    auth = "bearer" if token and enforce else "loopback"
    return normalize_item(
        {
            "instance_id": "fleet",
            "kind": "service",
            "purpose": "control",
            "label": "Forge Fleet",
            "status": "running",
            "auth": auth,
            "detail": "local control plane",
            "ttl_s": 45,
        }
    )


def refresh_runtime(conn: Any) -> None:
    """Refresh the Fleet row and running jobs. Drop workers that have finished."""
    upsert_local(conn, fleet_self_item())
    running = conn.execute("SELECT id, kind FROM jobs WHERE status = 'running'").fetchall()
    live = set()
    auth = fleet_self_item()["auth"]
    for row in running:
        jid = str(row["id"])
        kind = _clip(row["kind"] or "job", 64) or "job"
        item = normalize_item(
            {
                "instance_id": f"job:{jid}",
                "kind": "worker",
                "purpose": kind,
                "label": kind,
                "status": "running",
                "auth": auth,
                "detail": jid,
                "ttl_s": 45,
            }
        )
        upsert_local(conn, item)
        live.add(item["instance_id"])
    stale = conn.execute(
        """
        SELECT instance_id FROM presence
        WHERE node_id = ? AND origin = 'local' AND kind = 'worker' AND instance_id LIKE 'job:%'
        """,
        (local_node_id(),),
    ).fetchall()
    for row in stale:
        iid = str(row["instance_id"])
        if iid not in live:
            delete_instance(conn, iid)
    conn.commit()


def sync_job_presence(conn: Any, job_id: str) -> None:
    row = conn.execute("SELECT id, kind, status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        delete_instance(conn, f"job:{job_id}")
        conn.commit()
        return
    status = str(row["status"] or "")
    if status in _TERMINAL_JOB or status != "running":
        delete_instance(conn, f"job:{row['id']}")
        conn.commit()
        return
    refresh_runtime(conn)


def _uplink_target_is_self(base_url: str) -> bool:
    host = base_url.split("://", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0].lower()
    me = {local_node_id().lower(), socket.gethostname().lower(), "127.0.0.1", "localhost"}
    return host in me


def maybe_uplink(conn: Any, data_dir: Any) -> dict[str, Any]:
    peer_id = upstream_peer_id()
    if not peer_id or peer_id == local_node_id().lower():
        return {"ok": True, "skipped": "main"}
    peer = remote_peers.get_peer(data_dir, peer_id)
    if not peer:
        return {"ok": True, "skipped": "no_peer"}
    base = str(peer.get("base_url") or "").rstrip("/")
    if not base or _uplink_target_is_self(base):
        return {"ok": True, "skipped": "self"}
    items = local_items(conn)
    payload = encode_aggregate(local_node_id(), items)
    req = urllib.request.Request(
        base + "/v1/presence/aggregate",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
            "Accept": "application/json",
            "Authorization": "Bearer " + str(peer.get("bearer_token") or "").strip(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as ex:
        return {"ok": False, "error": f"http_{ex.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        return {"ok": False, "error": str(ex)[:200]}
    return {"ok": True, "bytes": len(payload), "response": raw[:200]}


def start_loops(db_path: Any, data_dir: Any) -> None:
    global _started
    with _started_lock:
        if _started:
            return
        _started = True

    def _loop() -> None:
        from fleet_server import store

        last_uplink = 0.0
        while True:
            try:
                conn = store.connect(db_path)
                try:
                    refresh_runtime(conn)
                    now = time.time()
                    if now - last_uplink >= _UPLINK_EVERY_S:
                        maybe_uplink(conn, data_dir)
                        last_uplink = now
                finally:
                    conn.close()
            except Exception:
                pass
            time.sleep(_TICK_S)

    threading.Thread(target=_loop, name="fleet-presence", daemon=True).start()
